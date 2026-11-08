# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic conservative findings, reversible decisions, freshness and text retention."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from openworld_moments.media.tools import MediaTools
from openworld_moments.privacy.service import (
    PrivacyConfig,
    PrivacyError,
    PrivacyReviewService,
    ReviewChange,
    SpoilerRange,
    patterns,
    source_ranges,
)
from openworld_moments.render.plan import RenderError
from openworld_moments.render.service import Renderer
from tests.exports.conftest import AST, DOCUMENT, PRJ, SES, Fixture
from tests.privacy.helpers import acknowledge


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Call +1 202-555-0186", ["phone"]),
        ("Call (202) 555-0186", ["phone"]),
        ("@Synthetic_Player", ["username"]),
        ("Gamertag: Fixture42", ["username"]),
        ("2025550186", []),
        ("Score: 1234567890", []),
        ("X: 202.555 Y: 0186", []),
        ("123,456,789", []),
        ("2026-11-08", []),
        ("contact@example.test", []),
        ("Username: Abc", ["username"]),
        ("Grand finale", ["spoiler"]),
        ("FinaleScore", []),
    ],
)
def test_patterns(text: str, expected: list[str]) -> None:
    assert [c for c, _ in patterns(text, ["finale"])] == expected


def test_exact_ranges_and_manual_spoilers(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    project.sql("UPDATE media_assets SET audio_codec='aac' WHERE id=?", (AST,))
    project.sql(
        "INSERT INTO "
        "transcript_segments(session_id,start_ms,end_ms,text,confidence,"
        "asset_id,source_start_ms,source_end_ms) "
        "VALUES(?,14000,15000,'Call 202-555-0186 @Fixture_User',.9,?,14000,15000)",
        (SES, AST),
    )
    report = service.configure(
        PRJ,
        PrivacyConfig(
            labels=["finale"], ranges=[SpoilerRange(start_ms=0, end_ms=500, label="Ending scene")]
        ),
    )
    categories = {f["category"] for f in report["flags"]}
    assert {"phone", "username", "subtitle", "speech", "mixed_audio", "spoiler"} <= categories
    phone = next(f for f in report["flags"] if f["category"] == "phone")
    assert (
        phone["start_ms"],
        phone["end_ms"],
        phone["source_start_ms"],
        phone["source_end_ms"],
    ) == (1500, 2500, 14000, 15000)
    assert all(
        f["start_ms"] < f["end_ms"] and f["evidence"] and f["evidence_kind"]
        for f in report["flags"]
    )
    assert not report["current"]
    # Repeat source cuts each get their own exact timeline finding.
    doc = copy.deepcopy(DOCUMENT)
    cut = doc["project"]["tracks"][0]["segments"][0]
    cut2 = copy.deepcopy(cut)
    cut2.update(id="seg_01JCBQ00000000000000000009", timeline_start_ms=43300)
    doc["project"]["tracks"][0]["segments"].append(cut2)
    spans = source_ranges(doc, AST, 14000, 15000)
    assert [s["start_ms"] for s in spans] == [1500, 44800]


def change(
    report: dict[str, Any], state: str = "ignore", acknowledged: bool = True
) -> ReviewChange:
    return ReviewChange.model_validate(
        dict(
            token=report["token"],
            acknowledged=acknowledged,
            decisions=[dict(id=f["id"], state=state) for f in report["flags"]],
        )
    )


def test_decisions_persist_reverse_and_gate_every_export(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    service.clear(PRJ)
    for fmt in ("project", "events", "srt", "vtt", "csv", "otio", "fcpxml"):
        with pytest.raises(PrivacyError, match="Complete privacy"):
            project.exporter.project(PRJ, fmt)
    with pytest.raises(RenderError) as error:
        Renderer(project.database, MediaTools()).check_request(
            dict(project_id=PRJ, preset_id="horizontal-720p30")
        )
    assert error.value.code == "privacy.review_required"
    report = service.get(PRJ)
    assert not service.decide(PRJ, change(report, acknowledged=False))["current"]
    report = service.decide(PRJ, change(report))
    assert report["current"]
    assert PrivacyReviewService(project.database).get(PRJ) == report
    for fmt in ("project", "events", "srt", "vtt", "csv", "otio", "fcpxml"):
        result = project.exporter.project(PRJ, fmt)
        assert (
            result["privacy_review"]["acknowledged"] and result["privacy_review"]["unresolved"] == 0
        )
    restored = service.decide(PRJ, change(report, "unresolved"))
    assert not restored["current"]
    with pytest.raises(PrivacyError):
        project.exporter.project(PRJ, "project")


def test_changed_document_evidence_and_config_invalidate(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    old = service.get(PRJ)
    assert old["current"]
    doc = copy.deepcopy(DOCUMENT)
    doc["project"]["audio"]["gain_db"] = -4
    project.save(doc, revision=4)
    assert not service.get(PRJ)["current"]
    with pytest.raises(PrivacyError) as error:
        service.decide(PRJ, change(old))
    assert error.value.code == "privacy.stale_review"
    acknowledge(project.database, PRJ)
    project.sql("UPDATE events SET confidence=.8 WHERE session_id=?", (SES,))
    assert not service.get(PRJ)["current"]
    acknowledge(project.database, PRJ)
    new = service.configure(PRJ, PrivacyConfig(labels=["finale"], ranges=[]))
    assert not new["current"]
    assert not service.get(PRJ)["summary"]["acknowledged"]


def test_ocr_and_subtitle_evidence(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    project.sql(
        "UPDATE events SET "
        "type='openworld.subtitle',evidence_json=?,attributes_json=? "
        "WHERE id='evt_01JCBQ00000000000000000031'",
        (
            json.dumps(
                [
                    dict(
                        kind="ocr",
                        text="finale @PlayerFixture",
                        score=0.9,
                        region=[0.1, 0.8, 0.8, 0.1],
                        frame_ms=21000,
                    )
                ]
            ),
            json.dumps(dict(spoiler_risk=True)),
        ),
    )
    report = service.get(PRJ)
    flags = [f for f in report["flags"] if f["evidence_kind"] == "ocr"]
    assert {f["category"] for f in flags} == {"subtitle", "username", "spoiler"}
    assert {(f["start_ms"], f["end_ms"]) for f in flags} == {(7500, 9500)}
    assert all(f["region"] == [0.1, 0.8, 0.8, 0.1] for f in flags)


def test_partial_or_duplicate_decisions_refused(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    report = service.get(PRJ)
    request = change(report)
    request.decisions = []
    with pytest.raises(PrivacyError):
        service.decide(PRJ, request)
    request = change(report)
    request.decisions.append(request.decisions[0])
    with pytest.raises(PrivacyError):
        service.decide(PRJ, request)


@pytest.mark.parametrize(
    "bad",
    [
        dict(labels=[""], ranges=[]),
        dict(labels=["a" * 101], ranges=[]),
        dict(labels=[], ranges=[dict(start_ms=2, end_ms=1, label="bad")]),
    ],
)
def test_invalid_configuration(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PrivacyConfig.model_validate(bad)


def test_deletion_removes_text_and_decisions_but_never_source(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    source = next(project.media.iterdir())
    before = source.read_bytes(), source.stat().st_mtime_ns
    project.sql(
        "INSERT INTO "
        "transcript_segments(session_id,start_ms,end_ms,text,confidence,"
        "asset_id,source_start_ms,source_end_ms) "
        "VALUES(?,14000,15000,'Private synthetic phrase',.9,?,14000,15000)",
        (SES, AST),
    )
    # Review rows contain only hashes/categories/choices, never copied evidence text.
    acknowledge(project.database, PRJ)
    with project.database.connect() as conn:
        row = conn.execute(
            "SELECT decisions_json FROM privacy_reviews WHERE project_id=?", (PRJ,)
        ).fetchone()[0]
        assert "Private synthetic phrase" not in row
    assert service.delete_text(PRJ) == {"deleted": True}
    with project.database.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM transcript_segments WHERE session_id=?", (SES,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM events WHERE session_id=? AND "
                "json_type(attributes_json,'$.text') IS NOT NULL",
                (SES,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM privacy_reviews WHERE project_id=?", (PRJ,)
            ).fetchone()[0]
            == 0
        )
        row = conn.execute(
            "SELECT document_json,recovery_json FROM editor_projects WHERE project_id=?", (PRJ,)
        ).fetchone()
        assert json.loads(row[0])["project"]["captions"] == [] and row[1] is None
        assert (
            conn.execute(
                "SELECT count(*) FROM search_documents WHERE body LIKE '%Private synthetic phrase%'"
            ).fetchone()[0]
            == 0
        )
    assert before == (source.read_bytes(), source.stat().st_mtime_ns)
    assert not service.get(PRJ)["current"]


def test_clear_only_review_keeps_captions(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    service.clear(PRJ)
    assert service.projects.get(PRJ)["document"]["project"]["captions"]
    assert not service.get(PRJ)["current"]


def test_session_text_outside_the_cut_is_reviewed_before_event_export(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    project.sql(
        "UPDATE events SET evidence_json=? WHERE id='evt_01JCBQ00000000000000000032'",
        (
            json.dumps(
                [dict(kind="ocr", text="Call 202-555-0186", score=0.9, region=[0, 0, 0.3, 0.1])]
            ),
        ),
    )
    report = service.get(PRJ)
    phone = next(f for f in report["flags"] if f["category"] == "phone")
    assert phone["time_domain"] == "session"
    assert (phone["start_ms"], phone["end_ms"]) == (5000, 6000)
    assert report["session_id"] == SES
    assert not report["current"]


def test_queued_analysis_prevents_text_purge_and_can_be_cancelled(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    jid = "job_01JCBQ00000000000000000088"
    project.sql(
        "INSERT INTO jobs(id,kind,state,params_json,created_at) "
        "VALUES(?,'analyze','queued',?,'2026-11-08T00:00:00Z')",
        (jid, json.dumps(dict(session_id=SES))),
    )
    with pytest.raises(PrivacyError) as error:
        service.delete_text(PRJ)
    assert error.value.code == "privacy.jobs_active"
    assert service.projects.get(PRJ)["document"]["project"]["captions"]
    project.sql("UPDATE jobs SET state='cancelled' WHERE id=?", (jid,))
    assert service.delete_text(PRJ)["deleted"]


def test_excess_findings_and_outside_spoiler_configuration_fail_closed(project: Fixture) -> None:
    service = PrivacyReviewService(project.database)
    before = service.get(PRJ)["config"]
    with pytest.raises(PrivacyError) as error:
        service.configure(
            PRJ,
            PrivacyConfig(
                labels=[], ranges=[SpoilerRange(start_ms=0, end_ms=999999, label="outside")]
            ),
        )
    assert error.value.code == "privacy.range_outside_project"
    assert service.get(PRJ)["config"] == before
    document = copy.deepcopy(DOCUMENT)
    document["project"]["captions"] = [
        dict(start_ms=0, end_ms=1, text=f"Synthetic subtitle {i}") for i in range(2001)
    ]
    project.save(document)
    with pytest.raises(PrivacyError) as error:
        service.get(PRJ)
    assert error.value.code == "privacy.too_many_findings"


def test_render_execution_rechecks_review_before_reading_media(project: Fixture) -> None:
    from openworld_moments.render.service import RenderFailed

    service = PrivacyReviewService(project.database)
    service.clear(PRJ)
    renderer = Renderer(project.database, MediaTools())
    with pytest.raises(RenderFailed) as error:
        renderer.run(
            dict(project_id=PRJ, preset_id="horizontal-720p30"),
            job_id="job_01JCBQ00000000000000000089",
        )
    record = error.value.record
    assert record["status"] == "failed" and record["error"]["code"] == "privacy.review_required"
    assert not list((renderer.root / "renders").glob("**/*.mp4"))
