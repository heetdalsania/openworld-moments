# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from openworld_moments.review.service import (
    EventReviewService,
    ManualEvent,
    ReviewChange,
    ReviewError,
)
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import EventRepository, SessionRepository
from tests.detectors.test_runtime import events, run
from tests.detectors.test_runtime import rig as rig


def test_corrections_are_separate_and_reanalysis_keeps_history(rig: Any) -> None:
    analyzer, sid, _ = rig
    run(analyzer, sid)
    review = EventReviewService(analyzer.database)
    page = review.page(sid)
    item = page["items"][0]
    eid = item["original"]["id"]
    original = events(analyzer, sid)[0]

    def change(
        action: Literal["approve", "reject", "reset", "correct"], revision: int, **fields: Any
    ) -> dict[str, Any]:
        return review.change(
            sid,
            eid,
            ReviewChange(
                layout_key=page["layout_key"], expected_revision=revision, action=action, **fields
            ),
        )

    changed = change("correct", 0, type="openworld.corrected", start_ms=100, end_ms=900)
    assert changed["effective"]["type"] == "openworld.corrected"
    assert changed["original"] == original and events(analyzer, sid)[0] == original
    approved = change("approve", 1)
    assert (
        approved["effective"]["review_state"] == "confirmed"
        and approved["effective"]["start_ms"] == 100
    )
    rejected = change("reject", 2)
    assert rejected["effective"]["review_state"] == "rejected"
    reset = change("reset", 3)
    assert reset["effective"] == original and len(reset["history"]) == 4
    with pytest.raises(ReviewError, match="Another review"):
        change("approve", 0)
    change("correct", 4, type="openworld.corrected", start_ms=100, end_ms=900)
    manual = review.manual(
        sid,
        ManualEvent(
            layout_key=page["layout_key"], type="openworld.manual", start_ms=1000, end_ms=2000
        ),
    )
    run(analyzer, sid, force=True)
    after = review.page(sid)
    old = next(i for i in after["items"] if i["original"]["id"] == eid)
    assert old["status"] == "superseded" and old["effective"]["type"] == "openworld.corrected"
    assert old["original"] == original
    assert (
        next(i for i in after["items"] if i["original"]["id"] == manual["original"]["id"])["status"]
        == "current"
    )
    assert (
        len(
            [
                i
                for i in after["items"]
                if i["status"] == "current" and i["original"]["source"]["kind"] == "detector"
            ]
        )
        == 1
    )
    with pytest.raises(ReviewError, match="historical"):
        change("approve", 5)
    with contextlib.closing(analyzer.database.connect()) as conn:
        assert conn.execute(
            "SELECT original_json FROM event_observations WHERE event_id=?", (eid,)
        ).fetchone()
        assert SessionRepository(conn).has_attached_data(sid)
    SessionService(analyzer.database).recompute({})
    assert review.page(sid)["total"] >= 2


def test_stale_layout_legacy_and_bounds_fail_closed(rig: Any) -> None:
    analyzer, sid, _ = rig
    run(analyzer, sid)
    review = EventReviewService(analyzer.database)
    page = review.page(sid)
    eid = page["items"][0]["original"]["id"]
    for a, b in ((100, 100), (200, 100), (0, page["duration_ms"] + 1)):
        with pytest.raises(ReviewError, match="interval"):
            review.manual(
                sid,
                ManualEvent(
                    layout_key=page["layout_key"], type="openworld.manual", start_ms=a, end_ms=b
                ),
            )
    with pytest.raises(ReviewError, match="session changed"):
        review.manual(
            sid, ManualEvent(layout_key="f" * 64, type="openworld.manual", start_ms=0, end_ms=10)
        )
    with contextlib.closing(analyzer.database.connect()) as conn:
        conn.execute("UPDATE media_assets SET duration_ms=duration_ms+1000")
    assert review.page(sid)["items"][0]["status"] == "stale"
    with pytest.raises(ReviewError, match="session changed"):
        review.change(
            sid,
            eid,
            ReviewChange(layout_key=page["layout_key"], expected_revision=0, action="approve"),
        )
    # A pre-M19 observation is inspectable, but cannot silently acquire current timing.
    with contextlib.closing(analyzer.database.connect()) as conn:
        conn.execute("DELETE FROM event_observations WHERE event_id=?", (eid,))
    legacy = review.page(sid)
    assert legacy["items"][0]["status"] == "legacy"
    with pytest.raises(ReviewError, match="stale timing"):
        review.change(
            sid,
            eid,
            ReviewChange(layout_key=legacy["layout_key"], expected_revision=0, action="approve"),
        )
    with pytest.raises(ValidationError):
        ReviewChange.model_validate(
            {
                "layout_key": page["layout_key"],
                "expected_revision": 0,
                "action": "approve",
                "confidence": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReviewChange(layout_key=page["layout_key"], expected_revision=0, action="correct")


def test_history_is_bounded_on_read_and_immutable_original_survives(rig: Any) -> None:
    analyzer, sid, _ = rig
    run(analyzer, sid)
    review = EventReviewService(analyzer.database)
    page = review.page(sid)
    eid = page["items"][0]["original"]["id"]
    for n in range(25):
        review.change(
            sid,
            eid,
            ReviewChange(layout_key=page["layout_key"], expected_revision=n, action="approve"),
        )
    item = review.page(sid)["items"][0]
    assert item["history_truncated"] and [d["revision"] for d in item["history"]] == list(
        range(6, 26)
    )
    with contextlib.closing(analyzer.database.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM event_decisions").fetchone()[0] == 25
        assert EventRepository(conn).get(eid).review_state == "unreviewed"


def test_failed_cancelled_and_empty_reruns_preserve_decisions(
    rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from openworld_moments.detectors import service as module
    from openworld_moments.detectors.example import BrightRegion
    from openworld_moments.detectors.sdk import AnalysisCancelled, AnalysisError

    analyzer, sid, _ = rig
    run(analyzer, sid)
    review = EventReviewService(analyzer.database)
    before = review.page(sid)
    eid = before["items"][0]["original"]["id"]
    review.change(
        sid,
        eid,
        ReviewChange(layout_key=before["layout_key"], expected_revision=0, action="approve"),
    )
    original = review.page(sid)["items"][0]

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AnalysisError("analysis.decode_failed", "Derived samples unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(module, "decode_frames", fail)
        assert run(analyzer, sid, force=True)["outcomes"][0]["status"] == "failed"
    assert review.page(sid)["items"][0] == original
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AnalysisCancelled):
        analyzer.run(
            {"session_id": sid, "profile_id": "generic-open-world", "force": True},
            job_id="job_unused",
            cancel=cancel,
        )
    assert review.page(sid)["items"][0] == original
    monkeypatch.setattr(BrightRegion, "detect", lambda self, context: iter(()))
    assert run(analyzer, sid, force=True)["outcomes"][0]["event_ids"] == []
    assert review.page(sid)["items"][0]["status"] == "superseded"
    with contextlib.closing(analyzer.database.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert SessionRepository(conn).has_attached_data(sid)
    SessionService(analyzer.database).recompute({})
    assert review.page(sid)["items"][0]["revision"] == 1
