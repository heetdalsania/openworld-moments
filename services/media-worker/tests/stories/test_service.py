# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.detectors.profiles import canonical
from openworld_moments.ids import new_id
from openworld_moments.review.service import (
    EventReviewService,
    ManualEvent,
    ReviewChange,
    layout_info,
)
from openworld_moments.review.service import snapshot as event_snapshot
from openworld_moments.sessions.fixtures import Clip, at, install
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import (
    Database,
    EventRepository,
    SessionRepository,
    StoryRepository,
    transaction,
)
from openworld_moments.stories import algorithm
from openworld_moments.stories.service import (
    StoryCancelled,
    StoryDecision,
    StoryError,
    StoryRequest,
    StoryService,
    snapshot,
)


@pytest.fixture
def library(tmp_path: Path) -> tuple[Database, str, str]:
    db = Database.open(tmp_path / "library" / "database.sqlite3")
    with contextlib.closing(db.connect()) as conn:
        ids = install(conn, [Clip("synthetic.mp4", at(0), duration_s=120)])
    sessions = SessionService(db)
    sessions.recompute({})
    with contextlib.closing(db.connect()) as conn:
        sid = sessions.list_docs(conn, limit=1, offset=0)[0]["id"]
    return db, sid, ids[0]


def manual(db: Database, sid: str, start: int = 20000, end: int = 22000) -> dict[str, Any]:
    review = EventReviewService(db)
    return review.manual(
        sid,
        ManualEvent(
            layout_key=review.page(sid)["layout_key"],
            type="openworld.mission_completed",
            start_ms=start,
            end_ms=end,
        ),
    )


def first(service: StoryService, sid: str) -> dict[str, Any]:
    return dict(service.page(sid, StoryRequest())["items"][0])


def decide(service: StoryService, sid: str, item: dict[str, Any], state: Any) -> dict[str, Any]:
    return service.decide(
        sid,
        item["candidate"]["id"],
        StoryDecision(
            input_key=item["candidate"]["input_key"],
            expected_revision=item["revision"],
            state=state,
        ),
    )


def test_persistence_review_regeneration_and_non_destructive_project_handoff(library: Any) -> None:
    db, sid, _ = library
    service = StoryService(db)
    original = manual(db, sid)
    result = service.generate(sid, StoryRequest())
    assert result["candidate_count"] == 1 and not result["cached"]
    item = first(service, sid)
    candidate = item["candidate"]
    assert candidate["source_events"][0]["event_id"] == original["original"]["id"]
    assert service.generate(sid, StoryRequest())["cached"]
    rejected = decide(service, sid, item, "rejected")
    assert rejected["revision"] == 1 and service.page(sid, StoryRequest())["total"] == 0
    service.generate(sid, StoryRequest(force=True))
    history = service.page(sid, StoryRequest(), include_history=True)
    assert history["items"][0]["review_state"] == "rejected"
    restored = decide(service, sid, rejected, "suggested")
    accepted = decide(service, sid, restored, "accepted")
    assert accepted["project_id"] == candidate["id"]
    with contextlib.closing(db.connect()) as conn:
        project = StoryRepository(conn).get(candidate["id"])
        before = canonical(project.timeline.model_dump(mode="json", exclude_unset=True))
        assert project.review_state == "accepted"
        assert conn.execute("SELECT count(*) FROM story_decisions").fetchone()[0] == 3
    # Restart and force regeneration cannot modify accepted edits/decisions.
    service = StoryService(Database.open(db.path))
    service.generate(sid, StoryRequest(force=True))
    assert first(service, sid)["candidate"] == candidate
    with contextlib.closing(db.connect()) as conn:
        assert (
            canonical(
                StoryRepository(conn)
                .get(candidate["id"])
                .timeline.model_dump(mode="json", exclude_unset=True)
            )
            == before
        )
        conn.execute("UPDATE stories SET review_state='edited' WHERE id=?", (candidate["id"],))
    with pytest.raises(StoryError, match="editor changes"):
        decide(service, sid, accepted, "rejected")
    with pytest.raises(StoryError, match="review changed"):
        decide(service, sid, item, "accepted")


def test_invalidation_review_layout_transcript_and_generator(
    library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, sid, aid = library
    manual(db, sid)
    service = StoryService(db)
    service.generate(sid, StoryRequest())
    item = first(service, sid)
    review = EventReviewService(db)
    page = review.page(sid)
    e = page["items"][0]
    review.change(
        sid,
        e["original"]["id"],
        ReviewChange(
            layout_key=page["layout_key"],
            expected_revision=0,
            action="correct",
            type="openworld.mission_completed",
            start_ms=25000,
            end_ms=27000,
        ),
    )
    assert service.page(sid, StoryRequest())["total"] == 0
    with pytest.raises(StoryError, match="Evidence or generator changed"):
        decide(service, sid, item, "accepted")
    service.generate(sid, StoryRequest())
    new = first(service, sid)
    assert new["candidate"]["id"] != item["candidate"]["id"]
    monkeypatch.setattr(algorithm, "GENERATOR_VERSION", "1.0.1")
    assert service.page(sid, StoryRequest())["total"] == 0
    service.generate(sid, StoryRequest())
    versioned = first(service, sid)
    assert versioned["candidate"]["generator"]["version"] == "1.0.1"
    with contextlib.closing(db.connect()) as conn:
        conn.execute(
            "INSERT INTO "
            "transcript_segments(session_id,asset_id,start_ms,"
            "end_ms,source_start_ms,source_end_ms,text,words_json,transcriber_json) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (sid, aid, 1, 2, 20000, 45000, "PRIVATE SENTENCE.", "[]", "{}"),
        )
    assert not first_history(service, sid, versioned["candidate"]["id"])["current"]
    service.generate(sid, StoryRequest())
    spoken = first(service, sid)
    assert spoken["candidate"]["end_ms"] >= 45000
    assert "PRIVATE" not in canonical(spoken)
    with contextlib.closing(db.connect()) as conn:
        conn.execute("UPDATE media_assets SET duration_ms=duration_ms+1000 WHERE id=?", (aid,))
    assert service.page(sid, StoryRequest())["total"] == 0
    assert all(
        not x["current"] for x in service.page(sid, StoryRequest(), include_history=True)["items"]
    )


def first_history(service: StoryService, sid: str, cid: str) -> dict[str, Any]:
    return next(
        i
        for i in service.page(sid, StoryRequest(), include_history=True)["items"]
        if i["candidate"]["id"] == cid
    )


def test_cancel_failure_and_input_race_commit_nothing(
    library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, sid, _ = library
    manual(db, sid)
    service = StoryService(db)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(StoryCancelled):
        service.generate(sid, StoryRequest(), cancel=cancel)
    cancel.clear()

    def progress(done: int, *_: Any) -> None:
        if done == 2:
            cancel.set()

    with pytest.raises(StoryCancelled):
        service.generate(sid, StoryRequest(), cancel=cancel, progress=progress)
    assert service.page(sid, StoryRequest())["total"] == 0

    def race(done: int, *_: Any) -> None:
        if done == 2:
            manual(db, sid, 50000, 51000)

    with pytest.raises(StoryError, match="evidence changed"):
        service.generate(sid, StoryRequest(), progress=race)
    assert service.page(sid, StoryRequest())["total"] == 0

    def broken(*_: Any) -> Any:
        raise RuntimeError("Synthetic failure")

    monkeypatch.setattr(algorithm, "generate", broken)
    with pytest.raises(RuntimeError):
        service.generate(sid, StoryRequest())
    with contextlib.closing(db.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM story_candidates").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM story_generations").fetchone()[0] == 0


def test_no_events_legacy_rejected_and_audio_only_do_not_fabricate_stories(library: Any) -> None:
    db, sid, aid = library
    service = StoryService(db)
    assert service.generate(sid, StoryRequest())["candidate_count"] == 0
    assert service.generate(sid, StoryRequest())["cached"]
    e = manual(db, sid)
    review = EventReviewService(db)
    review.change(
        sid,
        e["original"]["id"],
        ReviewChange(
            layout_key=review.page(sid)["layout_key"], expected_revision=0, action="reject"
        ),
    )
    assert service.generate(sid, StoryRequest())["candidate_count"] == 0
    audio = {
        "schema_version": "1.15",
        "id": new_id("evt"),
        "session_id": sid,
        "asset_id": aid,
        "type": "openworld.audio_impact",
        "start_ms": 10000,
        "end_ms": 11000,
        "confidence": 1,
        "attributes": {},
        "evidence": [
            {
                "kind": "audio",
                "start_ms": 10000,
                "end_ms": 11000,
                "score": 1,
                "feature": "impact",
                "role": "supporting",
            }
        ],
        "source": {
            "kind": "detector",
            "detector_id": "audio-features",
            "detector_version": "1.0.0",
            "profile_id": "generic-audio",
            "profile_version": "1.0.0",
        },
        "review_state": "unreviewed",
    }
    with contextlib.closing(db.connect()) as conn, transaction(conn):
        EventRepository(conn).add(load("event", audio))  # type: ignore[arg-type]
        event_snapshot(conn, audio, layout_info(conn, sid)[0])
    page = review.page(sid)
    review.change(
        sid,
        audio["id"],
        ReviewChange(
            layout_key=page["layout_key"],
            expected_revision=0,
            action="correct",
            type="openworld.vehicle_crash",
            start_ms=10000,
            end_ms=11000,
        ),
    )
    assert service.generate(sid, StoryRequest())["candidate_count"] == 0
    # Pre-M19 events cannot become seeds without a proven producing layout.
    legacy = {
        **audio,
        "id": new_id("evt"),
        "type": "openworld.mission_completed",
        "evidence": [{"kind": "temporal_consistency", "frames": 2, "score": 1}],
        "source": {"kind": "user"},
    }
    with contextlib.closing(db.connect()) as conn:
        EventRepository(conn).add(load("event", legacy))  # type: ignore[arg-type]
    assert service.generate(sid, StoryRequest())["candidate_count"] == 0


def test_source_transcript_remapping_and_cli(library: Any) -> None:
    db, sid, aid = library
    manual(db, sid)
    service = StoryService(db)
    with contextlib.closing(db.connect()) as conn:
        conn.execute(
            "INSERT INTO "
            "transcript_segments(session_id,asset_id,start_ms,"
            "end_ms,source_start_ms,source_end_ms,text,words_json,transcriber_json) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (sid, aid, 90000, 95000, 6000, 35000, "Private utterance.", "[]", "{}"),
        )
        snap = snapshot(conn, sid, StoryRequest())
        assert snap["speech"] == [(6000, 35000)]
    library_path = db.path.parent
    command = [
        sys.executable,
        "-m",
        "openworld_moments.detectors",
        "story",
        sid,
        "--library",
        str(library_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603 - fixed interpreter, generated fixture library
    assert result.returncode == 0, result.stdout + result.stderr
    page = json.loads(result.stdout)
    assert page["items"]
    assert "Private utterance" not in result.stdout
    assert page["items"][0]["candidate"]["start_ms"] == 6000
    assert page["items"][0]["candidate"]["end_ms"] == 35000
    with contextlib.closing(db.connect()) as conn:
        assert SessionRepository(conn).has_attached_data(sid)
    assert service.page(sid, StoryRequest(), offset=2**100)["items"] == []


def test_cancel_during_insert_rolls_back_and_bounded_inputs_fail_closed(
    library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, sid, _ = library
    manual(db, sid)
    service = StoryService(db)
    cancel = threading.Event()
    connect = db.connect

    def hooked() -> Any:
        conn = connect()
        conn.create_function("cancel_story", 0, lambda: cancel.set())
        conn.execute(
            "CREATE TEMP TRIGGER story_cancel AFTER INSERT ON story_candidates "
            "BEGIN SELECT cancel_story(); END"
        )
        return conn

    monkeypatch.setattr(db, "connect", hooked)
    with pytest.raises(StoryCancelled):
        service.generate(sid, StoryRequest(), cancel=cancel)
    with contextlib.closing(connect()) as conn:
        assert conn.execute("SELECT count(*) FROM story_candidates").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM story_generations").fetchone()[0] == 0
    from openworld_moments.stories import service as module

    monkeypatch.setattr(module, "MAX_EVENTS", 0)
    with pytest.raises(StoryError, match="bounded"):
        service.generate(sid, StoryRequest())


def test_transcript_words_cross_clip_and_hidden_overlap_without_reusing_old_offsets(
    library: Any,
) -> None:
    db, sid, aid = library
    with contextlib.closing(db.connect()) as conn:
        other = install(conn, [Clip("second.mp4", at(2), duration_s=60)])[0]
        from openworld_moments.storage.repositories import SessionAsset

        SessionRepository(conn).replace_assets(
            sid,
            [
                SessionAsset(session_id=sid, asset_id=aid, order_index=0, session_start_ms=0),
                SessionAsset(
                    session_id=sid,
                    asset_id=other,
                    order_index=1,
                    session_start_ms=110000,
                    overlap_with_previous_ms=10000,
                ),
            ],
        )
        for asset, words in [
            (aid, [{"text": "Continued", "source_start_ms": 119000, "source_end_ms": 120000}]),
            (
                other,
                [
                    {"text": "Hidden.", "source_start_ms": 0, "source_end_ms": 9000},
                    {"text": "sentence.", "source_start_ms": 10000, "source_end_ms": 11000},
                ],
            ),
        ]:
            conn.execute(
                "INSERT INTO transcript_segments(session_id,asset_id,start_ms,end_ms,"
                "source_start_ms,source_end_ms,text,words_json,transcriber_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (sid, asset, 1, 2, 0, 120000, "Private", json.dumps(words), "{}"),
            )
        snap = snapshot(conn, sid, StoryRequest())
    assert snap["duration_ms"] == 170000
    assert snap["speech"] == [(119000, 121000)]
    assert snap["members"][1]["hidden_ms"] == 10000


def test_empty_generator_preserves_independent_manual_editor_projects(library: Any) -> None:
    from openworld_moments_contracts.generated.project_schema import Project

    from openworld_moments.storage.repositories import Story

    db, sid, aid = library
    cid = new_id("prj")
    project = Project.model_validate(
        {
            "schema_version": "1.15",
            "id": cid,
            "session_id": sid,
            "title": "Manual story",
            "created_at": "2026-11-07T22:00:00Z",
            "updated_at": "2026-11-07T22:00:00Z",
            "tracks": [
                {
                    "kind": "video",
                    "segments": [
                        {
                            "id": new_id("seg"),
                            "asset_id": aid,
                            "source_in_ms": 0,
                            "source_out_ms": 1000,
                            "timeline_start_ms": 0,
                            "crop": {"mode": "fit", "keyframes": []},
                        }
                    ],
                }
            ],
            "captions": [],
            "overlays": [],
            "audio": {"gain_db": 0, "mute_ranges": []},
        }
    )
    story = Story(
        id=cid,
        session_id=sid,
        title="Manual story",
        timeline=project,
        review_state="edited",
        created_at="2026-11-07T22:00:00Z",
        updated_at="2026-11-07T22:00:00Z",
    )
    with contextlib.closing(db.connect()) as conn:
        StoryRepository(conn).save(story)
    service = StoryService(db)
    assert service.generate(sid, StoryRequest())["candidate_count"] == 0
    with contextlib.closing(db.connect()) as conn:
        assert StoryRepository(conn).get(cid) == story
