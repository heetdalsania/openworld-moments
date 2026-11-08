# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session grouping (M11): capture-time estimation, the grouping fixture matrix,
idempotent recomputation, durable manual corrections, and the API."""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers, validate_group
from openworld_moments.media.tools import MediaTools
from openworld_moments.sessions import capture
from openworld_moments.sessions.fixtures import Clip, at, install, scenarios
from openworld_moments.sessions.service import SessionError, SessionService
from openworld_moments.storage import Database, SessionRepository, transaction
from tests.worker.conftest import wait_for

UTC_ZONE = ZoneInfo("UTC")


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "library" / "database.sqlite3")


@pytest.fixture
def service(database: Database) -> SessionService:
    return SessionService(database, zone=UTC_ZONE)


def load_scenario(database: Database, clips: list[Clip]) -> list[str]:
    with contextlib.closing(database.connect()) as conn:
        return install(conn, clips, zone=UTC_ZONE)


def sessions(service: SessionService) -> list[dict[str, Any]]:
    with contextlib.closing(service.database.connect()) as conn:
        docs = service.list_docs(conn, limit=1000, offset=0)
    for doc in docs:
        load("session", doc)  # contract-valid, including the semantic rules
    return sorted(docs, key=lambda d: d.get("started_at") or "")


def members(docs: list[dict[str, Any]]) -> list[list[str]]:
    return [[m["asset_id"] for m in d["assets"]] for d in docs]


# -- capture time ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Grand Theft Auto V 2026-11-20 03-14-22.mp4", datetime(2026, 11, 20, 3, 14, 22)),
        ("Grand Theft Auto V-2026_11_20-03_14_22.mp4", datetime(2026, 11, 20, 3, 14, 22)),
        ("Grand Theft Auto V_20261120031422.mp4", datetime(2026, 11, 20, 3, 14, 22)),
        ("VID_20261120_031422.mp4", datetime(2026, 11, 20, 3, 14, 22)),
        ("PXL_20261120_031422123.mp4", datetime(2026, 11, 20, 3, 14, 22)),
        ("Grand Theft Auto V 11_20_2026 3_14_22 PM.mp4", datetime(2026, 11, 20, 15, 14, 22)),
        ("Game 1_2_2027 12_05_00 AM.mp4", datetime(2027, 1, 2, 0, 5, 0)),
        ("2026-11-20T03:14:22.mkv", datetime(2026, 11, 20, 3, 14, 22)),
    ],
)
def test_filename_patterns(name: str, expected: datetime) -> None:
    parsed = capture.parse_filename(name)
    assert parsed is not None and parsed.local == expected


@pytest.mark.parametrize(
    "name",
    [
        "IMG_1234.MOV",
        "clip 2026-13-40 99-99-99.mp4",  # impossible date
        "a 2026-11-20 03-14-22 b 2026-11-21 04-00-00.mp4",  # two different times
        "Game 11_20_2026 13_14_22 PM.mp4",  # 13 PM
        "1999-01-01 00-00-00.mp4",  # outside 20xx
        "123456789012345678.mp4",
    ],
)
def test_no_time_is_invented_from_unclear_names(name: str) -> None:
    assert capture.parse_filename(name) is None


def _signals(
    name: str, container: datetime | None, mtime: datetime | None, duration_s: int = 60
) -> capture.Signals:
    return capture.Signals(
        name,
        capture.iso(container) if container else None,
        int(mtime.timestamp() * 1e9) if mtime else None,
        duration_s * 1000,
    )


def test_agreeing_signals_raise_confidence() -> None:
    start = datetime(2026, 11, 20, 3, 14, 22, tzinfo=UTC)
    name = "Heist 2026-11-20 03-14-22.mp4"
    only_name = capture.estimate(_signals(name, None, None), UTC_ZONE)
    with_container = capture.estimate(_signals(name, start, None), UTC_ZONE)
    all_three = capture.estimate(_signals(name, start, start + timedelta(seconds=60)), UTC_ZONE)
    assert only_name.captured_at == "2026-11-20T03:14:22.000Z"
    assert only_name.confidence < with_container.confidence < all_three.confidence <= 0.95
    assert all_three.basis == ("filename", "container_metadata", "filesystem_mtime")


def test_mtime_alone_is_weak_and_never_precise_looking() -> None:
    end = datetime(2026, 11, 20, 4, 0, 0, tzinfo=UTC)
    alone = capture.estimate(_signals("IMG_0001.MOV", None, end, duration_s=30), UTC_ZONE)
    assert alone.basis == ("filesystem_mtime",)
    assert alone.captured_at == "2026-11-20T03:59:30.000Z"  # end minus duration
    assert alone.confidence <= 0.25
    copied = capture.with_copy_artefact(alone)
    assert copied.confidence <= 0.1 and "copy time" in copied.notes[-1]


def test_whole_hour_disagreement_is_flagged_as_a_time_zone_problem() -> None:
    start = datetime(2026, 11, 20, 3, 14, 22, tzinfo=UTC)
    name = "Heist 2026-11-20 03-14-22.mp4"
    mismatch = capture.estimate(_signals(name, start + timedelta(hours=7), None), UTC_ZONE)
    agree = capture.estimate(_signals(name, start, None), UTC_ZONE)
    assert mismatch.confidence < capture.BASE_CONFIDENCE["filename"] < agree.confidence
    assert any("time-zone" in note for note in mismatch.notes)
    other = capture.estimate(_signals(name, start + timedelta(minutes=37), None), UTC_ZONE)
    assert other.confidence < capture.BASE_CONFIDENCE["filename"]
    assert any("disagrees" in note for note in other.notes)


@pytest.mark.parametrize(
    ("zone", "expected_utc"),
    [
        ("America/Los_Angeles", "2026-11-20T11:14:22.000Z"),  # PST, UTC-8
        ("America/Los_Angeles", None),  # see DST case below
        ("Asia/Kolkata", "2026-11-19T21:44:22.000Z"),  # UTC+5:30
        ("Europe/Berlin", "2026-11-20T02:14:22.000Z"),
    ],
)
def test_filename_times_use_the_local_zone(zone: str, expected_utc: str | None) -> None:
    result = capture.estimate(_signals("Heist 2026-11-20 03-14-22.mp4", None, None), ZoneInfo(zone))
    if expected_utc:
        assert result.captured_at == expected_utc
    # Daylight saving uses the rules of the recording's date, not today's.
    summer = capture.estimate(_signals("Heist 2026-07-01 12-00-00.mp4", None, None), ZoneInfo(zone))
    winter = capture.estimate(_signals("Heist 2026-12-01 12-00-00.mp4", None, None), ZoneInfo(zone))
    if zone == "America/Los_Angeles":
        assert summer.captured_at == "2026-07-01T19:00:00.000Z"  # PDT, UTC-7
        assert winter.captured_at == "2026-12-01T20:00:00.000Z"  # PST, UTC-8


def test_copy_artefacts_are_found_within_a_batch() -> None:
    base = 1_800_000_000_000_000_000
    flagged = capture.copy_artefacts([base, base + 500_000_000, base + 600 * 10**9, None])
    assert flagged == {0, 1}


# -- grouping matrix ------------------------------------------------------------------


def _group(
    service: SessionService, database: Database, name: str
) -> tuple[list[str], list[dict[str, Any]]]:
    ids = load_scenario(database, scenarios()[name])
    service.recompute({})
    return ids, sessions(service)


def test_same_source_adjacent_clips_group_deterministically(
    service: SessionService, database: Database
) -> None:
    ids, docs = _group(service, database, "adjacent_same_source")
    assert members(docs) == [ids]
    doc = docs[0]
    assert doc["review_state"] == "unreviewed"
    assert [m["session_start_ms"] for m in doc["assets"]] == [0, 180_000, 360_000]
    links = doc["grouping"]["links"]
    assert [link["reasons"] for link in links] == [
        ["same_source", "compatible_format", "gap_within_limit"]
    ] * 2
    assert all(link["gap_ms"] == 120_000 for link in links)
    assert doc["grouping"]["settings"] == {"max_gap_ms": 900_000}
    assert 0.6 < doc["grouping_confidence"] <= 0.95
    assert doc["started_at"] == "2026-11-20T03:00:00.000Z"
    assert doc["ended_at"] == "2026-11-20T03:07:00.000Z"


@pytest.mark.parametrize(
    ("scenario", "split"),
    [
        ("large_gap", "gap_exceeded"),
        ("format_change", "resolution_changed"),
    ],
)
def test_large_gaps_and_incompatible_formats_split(
    service: SessionService, database: Database, scenario: str, split: str
) -> None:
    ids, docs = _group(service, database, scenario)
    assert members(docs) == [[ids[0]], [ids[1]]]
    assert docs[1]["grouping"]["split_before"] == [split]


def test_different_folders_and_sources_stay_apart(
    service: SessionService, database: Database
) -> None:
    ids, docs = _group(service, database, "mixed_folders")
    assert sorted(members(docs)) == sorted([[ids[0]], [ids[1]]])
    database_two = Database.open(service.database.path.parent / "two.sqlite3")
    other = SessionService(database_two, zone=UTC_ZONE)
    ids2 = load_scenario(database_two, scenarios()["mixed_sources"])
    other.recompute({})
    assert sorted(members(sessions(other))) == sorted([[ids2[0]], [ids2[1]]])


def test_overlapping_replays_join(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "overlapping_replays")
    assert members(docs) == [ids]
    link = docs[0]["grouping"]["links"][0]
    assert link["gap_ms"] == -15_000 and "overlapping" in link["reasons"]


def test_exact_gap_boundary(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "boundary_gap")
    assert members(docs) == [ids[:2], ids[2:]]
    assert docs[0]["grouping"]["links"][0]["gap_ms"] == 900_000
    assert docs[1]["grouping"]["split_before"] == ["gap_exceeded"]


def test_unknown_times_group_by_import_order_with_low_confidence(
    service: SessionService, database: Database
) -> None:
    ids, docs = _group(service, database, "phone_copies_without_times")
    assert members(docs) == [ids]
    doc = docs[0]
    assert doc["grouping_confidence"] <= 0.15
    assert all("import_order" in link["reasons"] for link in doc["grouping"]["links"])
    assert any("copy time" in note for note in doc["grouping"]["notes"])
    for member in doc["assets"]:
        assert member["capture_time"]["confidence"] <= 0.1


def test_ambiguous_time_lowers_confidence(service: SessionService, database: Database) -> None:
    _, docs = _group(service, database, "timezone_mismatch")
    doc = docs[0]
    assert doc["grouping_confidence"] < capture.BASE_CONFIDENCE["filename"]
    assert any("time-zone" in note for note in doc["grouping"]["notes"])


def test_custom_gap_setting(service: SessionService, database: Database) -> None:
    ids = load_scenario(database, scenarios()["large_gap"])
    service.recompute({"max_gap_ms": 3 * 3600 * 1000})
    docs = sessions(service)
    assert members(docs) == [ids]
    assert docs[0]["grouping"]["settings"]["max_gap_ms"] == 10_800_000
    with pytest.raises(ValueError):
        validate_group({"max_gap_ms": 5})
    with pytest.raises(ValueError):
        validate_group({"gap": 1})


# -- recompute ------------------------------------------------------------------------


def test_recompute_is_idempotent(service: SessionService, database: Database) -> None:
    load_scenario(database, scenarios()["adjacent_same_source"] + scenarios()["large_gap"][1:])
    first = service.recompute({})
    assert first["sessions_created"] == 2
    before = sessions(service)
    second = service.recompute({})
    assert second == {
        "considered_assets": 4,
        "locked_assets": 0,
        "capture_times_updated": 0,
        "sessions_created": 0,
        "sessions_updated": 0,
        "sessions_unchanged": 2,
        "sessions_removed": 0,
    }
    assert sessions(service) == before  # same IDs, members, evidence, and timestamps


def test_new_clips_extend_sessions_and_keep_their_ids(
    service: SessionService, database: Database
) -> None:
    ids = load_scenario(database, scenarios()["adjacent_same_source"][:2])
    service.recompute({})
    session_id = sessions(service)[0]["id"]
    later = Clip("Heist 2026-11-20 03-06-00.mp4", at(6), container=at(6))
    with contextlib.closing(database.connect()) as conn:
        install(conn, [later], zone=UTC_ZONE)
    result = service.recompute({})
    assert result["sessions_updated"] == 1 and result["sessions_created"] == 0
    docs = sessions(service)
    assert docs[0]["id"] == session_id and len(docs[0]["assets"]) == 3
    assert members(docs)[0][:2] == ids


# -- corrections ----------------------------------------------------------------------


def test_split_survives_recomputation(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "adjacent_same_source")
    first, second = service.split(docs[0]["id"], ids[0])
    assert [m["asset_id"] for m in first["assets"]] == ids[:1]
    assert [m["asset_id"] for m in second["assets"]] == ids[1:]
    assert first["review_state"] == second["review_state"] == "corrected"
    assert first["grouping"] is None and first["grouping_confidence"] is None
    result = service.recompute({})
    assert result["locked_assets"] == 3 and result["sessions_created"] == 0
    assert sorted(members(sessions(service))) == sorted([ids[:1], ids[1:]])


def test_merge_survives_recomputation(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "large_gap")
    merged = service.merge([d["id"] for d in docs])
    assert [m["asset_id"] for m in merged["assets"]] == ids
    assert merged["id"] == docs[0]["id"] and merged["review_state"] == "corrected"
    service.recompute({})
    assert members(sessions(service)) == [ids]


def test_reorder_is_stable_and_places_clips_end_to_end(
    service: SessionService, database: Database
) -> None:
    ids, docs = _group(service, database, "adjacent_same_source")
    reordered = service.reorder(docs[0]["id"], [ids[2], ids[0], ids[1]])
    assert [m["asset_id"] for m in reordered["assets"]] == [ids[2], ids[0], ids[1]]
    assert [m["session_start_ms"] for m in reordered["assets"]] == [0, 60_000, 120_000]
    service.recompute({})
    again = sessions(service)[0]
    assert [m["asset_id"] for m in again["assets"]] == [ids[2], ids[0], ids[1]]
    with pytest.raises(SessionError):
        service.reorder(docs[0]["id"], [ids[0], ids[1]])  # not every member


def test_removed_clip_is_never_regrouped(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "adjacent_same_source")
    rest, alone = service.remove(docs[0]["id"], ids[1])
    assert [m["asset_id"] for m in rest["assets"]] == [ids[0], ids[2]]
    assert [m["asset_id"] for m in alone["assets"]] == [ids[1]]
    service.recompute({})
    assert sorted(members(sessions(service))) == sorted([[ids[0], ids[2]], [ids[1]]])


def test_confirmed_sessions_are_left_alone(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "adjacent_same_source")
    confirmed = service.confirm(docs[0]["id"])
    assert confirmed["review_state"] == "confirmed"
    later = Clip("Heist 2026-11-20 03-09-00.mp4", at(9), container=at(9))
    with contextlib.closing(database.connect()) as conn:
        new_id = install(conn, [later], zone=UTC_ZONE)[0]
    service.recompute({})
    docs = sessions(service)
    assert members(docs) == [ids, [new_id]]  # the new clip does not join a confirmed session


def test_corrections_are_logged(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "adjacent_same_source")
    sid = docs[0]["id"]
    service.reorder(sid, list(reversed(ids)))
    service.split(sid, ids[2])
    with contextlib.closing(database.connect()) as conn:
        log = service.corrections(conn, sid)
    assert [entry["kind"] for entry in log] == ["reorder", "split"]
    assert log[1]["detail"] == {"after_asset_id": ids[2]}


def test_bad_corrections_are_refused(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "large_gap")
    for call, code in (
        (lambda: service.split(docs[0]["id"], ids[0]), "session.invalid_request"),
        (lambda: service.split(docs[0]["id"], ids[1]), "session.invalid_request"),
        (lambda: service.merge([docs[0]["id"]]), "session.invalid_request"),
        (lambda: service.remove(docs[0]["id"], ids[1]), "session.invalid_request"),
        (lambda: service.confirm("ses_01JCBQ00000000000000000099"), "session.not_found"),
    ):
        with pytest.raises(SessionError) as caught:
            call()
        assert caught.value.code == code


def test_grouping_never_touches_media(
    service: SessionService, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_scenario(database, scenarios()["adjacent_same_source"])

    def no_files(*_: Any, **__: Any) -> None:
        raise AssertionError("grouping must not open files")

    monkeypatch.setattr("builtins.open", no_files)
    monkeypatch.setattr(Path, "open", no_files)
    result = service.recompute({})
    assert result["sessions_created"] == 1


def test_sessions_with_stories_are_locked(service: SessionService, database: Database) -> None:
    ids, docs = _group(service, database, "large_gap")
    with contextlib.closing(database.connect()) as conn, transaction(conn):
        conn.execute(
            "INSERT INTO stories (id, session_id, title, timeline_json, review_state, created_at, "
            "updated_at) VALUES ('prj_01JCBQ00000000000000000005', ?, 't', '{}', 'suggested', "
            "'2026-11-21T09:00:00Z', '2026-11-21T09:00:00Z')",
            (docs[0]["id"],),
        )
    result = service.recompute({"max_gap_ms": 3 * 3600 * 1000})
    assert result["locked_assets"] == 1
    assert sorted(members(sessions(service))) == sorted([[ids[0]], [ids[1]]])
    with contextlib.closing(database.connect()) as conn:
        assert SessionRepository(conn).has_stories(docs[0]["id"])


# -- job and API ----------------------------------------------------------------------


@pytest.fixture
def api(database: Database) -> Iterator[TestClient]:
    token = secrets.token_hex(32)
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    engine = JobEngine(database, build_handlers(MediaTools(), database=database))
    with TestClient(create_app(engine, settings)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


def test_session_api(api: TestClient, database: Database) -> None:
    ids = load_scenario(database, scenarios()["adjacent_same_source"])
    created = api.post("/v1/sessions/recompute", json={"idempotency_key": "group-1"})
    assert created.status_code == 201, created.text

    def done() -> dict[str, Any] | None:
        job: dict[str, Any] = api.get(f"/v1/jobs/{created.json()['id']}").json()
        return job if job["state"] in ("ready", "failed") else None

    job = wait_for(done, timeout=30)
    load("job", job)
    assert job["kind"] == "group" and job["state"] == "ready", job
    assert job["result"]["sessions_created"] == 1
    listed = api.get("/v1/sessions").json()
    assert len(listed) == 1
    sid = listed[0]["id"]
    assert api.get(f"/v1/sessions/{sid}").json() == listed[0]

    split = api.post(f"/v1/sessions/{sid}/split", json={"after_asset_id": ids[0]})
    assert split.status_code == 200 and len(split.json()) == 2
    other = split.json()[1]["id"]
    merged = api.post("/v1/sessions/merge", json={"session_ids": [sid, other]})
    assert merged.status_code == 200 and len(merged.json()["assets"]) == 3
    order = api.post(f"/v1/sessions/{sid}/order", json={"asset_ids": list(reversed(ids))})
    assert order.status_code == 200
    removed = api.post(f"/v1/sessions/{sid}/remove", json={"asset_id": ids[1]})
    assert removed.status_code == 200
    confirmed = api.post(f"/v1/sessions/{sid}/confirm")
    assert confirmed.json()["review_state"] == "corrected"  # corrected stays corrected
    log = api.get(f"/v1/sessions/{sid}/corrections").json()
    assert [entry["kind"] for entry in log] == ["split", "merge", "reorder", "remove", "confirm"]

    missing = api.get("/v1/sessions/ses_01JCBQ00000000000000000099")
    assert missing.status_code == 404 and missing.json()["code"] == "session.not_found"
    bad = api.post(f"/v1/sessions/{sid}/split", json={"after_asset_id": "nope"})
    assert bad.status_code == 422
    assert api.post("/v1/sessions/merge", json={"session_ids": [sid]}).status_code == 422
    assert api.post("/v1/sessions/recompute", json={"max_gap_ms": 5}).status_code == 422


# -- attached data is never dropped ---------------------------------------------------

NOW = "2026-11-21T09:00:00Z"
ATTACH = {
    "event": (
        "INSERT INTO events (id, session_id, type, start_ms, end_ms, confidence, "
        "attributes_json, evidence_json, source_kind, review_state) VALUES "
        "('evt_01JCBQ00000000000000000007', ?, 'wanted_level', 0, 1000, 0.9, '{}', '{}', "
        "'user', 'unreviewed')",
        "SELECT count(*) FROM events",
    ),
    "transcript": (
        "INSERT INTO transcript_segments (session_id, start_ms, end_ms, text) "
        "VALUES (?, 0, 1000, 'hello')",
        "SELECT count(*) FROM transcript_segments",
    ),
    "collection": (
        "INSERT INTO collection_items (collection_id, session_id, position, added_at) "
        "VALUES ('col_00000000000000000000000001', ?, 0, '2026-11-21T09:00:00Z')",
        "SELECT count(*) FROM collection_items",
    ),
}


def _attach(database: Database, kind: str, session_id: str) -> None:
    insert, _ = ATTACH[kind]
    with contextlib.closing(database.connect()) as conn, transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO collections (id, name, kind, created_at, updated_at) "
            "VALUES ('col_00000000000000000000000001', 'Best', 'manual', ?, ?)",
            (NOW, NOW),
        )
        conn.execute(insert, (session_id,))


def _count(database: Database, kind: str) -> int:
    with contextlib.closing(database.connect()) as conn:
        return int(conn.execute(ATTACH[kind][1]).fetchone()[0])


@pytest.mark.parametrize("kind", sorted(ATTACH))
def test_recompute_never_drops_attached_data(
    service: SessionService, database: Database, kind: str
) -> None:
    ids, docs = _group(service, database, "large_gap")
    _attach(database, kind, docs[1]["id"])
    # A wider gap would merge the two sessions, which would delete the second one.
    result = service.recompute({"max_gap_ms": 3 * 3600 * 1000})
    assert result["locked_assets"] == 1 and result["sessions_removed"] == 0
    after = sessions(service)
    assert docs[1]["id"] in {d["id"] for d in after}
    assert sorted(members(after)) == sorted([[ids[0]], [ids[1]]])
    assert _count(database, kind) == 1


@pytest.mark.parametrize("kind", sorted(ATTACH))
def test_merge_refuses_to_drop_attached_data(
    service: SessionService, database: Database, kind: str
) -> None:
    _, docs = _group(service, database, "large_gap")
    first, second = docs[0]["id"], docs[1]["id"]
    _attach(database, kind, second)
    with pytest.raises(SessionError) as caught:
        service.merge([first, second])
    assert caught.value.code == "session.in_use" and caught.value.status == 409
    assert _count(database, kind) == 1
    merged = service.merge([second, first])  # merging into it keeps everything
    assert merged["id"] == second and len(merged["assets"]) == 2
    assert _count(database, kind) == 1
