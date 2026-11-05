# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.event_schema import Event
from openworld_moments_contracts.generated.job_schema import Job
from openworld_moments_contracts.generated.media_asset_schema import MediaAsset
from openworld_moments_contracts.generated.project_schema import Project
from openworld_moments_contracts.validate import _canonical

from openworld_moments.storage import (
    AssetRepository,
    ConflictError,
    EventRepository,
    InUseError,
    JobRepository,
    NotFoundError,
    Session,
    SessionAsset,
    SessionRepository,
    SettingsRepository,
    Story,
    StoryRepository,
    transaction,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION
from tests.storage.conftest import contract_fixtures, read_json

# IDs used by the M01 contract fixtures.
ASSET_ID = "ast_01JCBQ00000000000000000001"
SESSION_ID = "ses_01JCBQ00000000000000000002"
PROJECT_ID = "prj_01JCBQ00000000000000000005"
OTHER_ASSET_ID = "ast_01JCBQ00000000000000000099"
NOW = "2026-11-20T05:40:10Z"
INSERT_SESSION = (
    "INSERT INTO sessions (id, title, review_state, created_at) VALUES (?, 't', '{state}', ?)"
)


def _asset(asset_id: str = ASSET_ID, sha: str = "3f" * 32) -> MediaAsset:
    doc = read_json(contract_fixtures("media-asset")[0])
    return load("media-asset", {**doc, "id": asset_id, "sha256": sha})  # type: ignore[return-value]


def _session(session_id: str = SESSION_ID) -> Session:
    return Session(id=session_id, title="Evening session", created_at=NOW)


def _expected(raw: dict[str, Any], **defaults: Any) -> Any:
    """What a repository returns for a stored fixture: current schema_version plus defaults."""
    return _canonical({**defaults, **raw, "schema_version": SCHEMA_VERSION})


def _seed(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        AssetRepository(conn).add(_asset(), original_path="/captures/a.mp4")
        SessionRepository(conn).add(_session())


def _story(project_doc: dict[str, Any]) -> Story:
    project: Project = load("project", project_doc)  # type: ignore[assignment]
    return Story(
        id=project.id,
        session_id=project.session_id,
        title=project.title,
        preset="short",
        score=0.82,
        score_components={"setup_coverage": 0.9, "payoff_coverage": 0.7},
        timeline=project,
        layout={"aspect": "9:16", "mode": "safe"},
        review_state="edited",
        created_at=NOW,
        updated_at=NOW,
    )


# -- round trips ----------------------------------------------------------------------


@pytest.mark.parametrize("path", contract_fixtures("media-asset"), ids=lambda p: p.stem)
def test_asset_round_trip_is_lossless(conn: sqlite3.Connection, path: Path) -> None:
    raw = read_json(path)
    repo = AssetRepository(conn)
    with transaction(conn):
        repo.add(load("media-asset", raw))  # type: ignore[arg-type]
    assert normalize(repo.get(raw["id"])) == _expected(raw)


@pytest.mark.parametrize("path", contract_fixtures("event"), ids=lambda p: p.stem)
def test_event_round_trip_is_lossless(conn: sqlite3.Connection, path: Path) -> None:
    _seed(conn)
    raw = read_json(path)
    repo = EventRepository(conn)
    with transaction(conn):
        repo.add(load("event", raw))  # type: ignore[arg-type]
    assert normalize(repo.get(raw["id"])) == _expected(raw)


@pytest.mark.parametrize("path", contract_fixtures("job"), ids=lambda p: p.stem)
def test_job_round_trip_is_lossless(conn: sqlite3.Connection, path: Path) -> None:
    raw = read_json(path)
    repo = JobRepository(conn)
    with transaction(conn):
        repo.save(load("job", raw))  # type: ignore[arg-type]
    assert normalize(repo.get(raw["id"])) == _expected(raw, attempt=1)


@pytest.mark.parametrize("path", contract_fixtures("project"), ids=lambda p: p.stem)
def test_story_round_trip_keeps_timeline_project(conn: sqlite3.Connection, path: Path) -> None:
    _seed(conn)
    raw = read_json(path)
    repo = StoryRepository(conn)
    story = _story(raw)
    with transaction(conn):
        repo.save(story)
    loaded = repo.get(story.id)
    assert loaded == story
    assert normalize(loaded.timeline) == _canonical(raw)


def test_job_save_replaces_state(conn: sqlite3.Connection) -> None:
    queued: Job = load("job", read_json(contract_fixtures("job")[-1]))  # type: ignore[assignment]
    repo = JobRepository(conn)
    with transaction(conn):
        repo.save(queued)
    assert [j.id for j in repo.list_unfinished()] == [queued.id]
    failed = {
        **normalize(queued),
        "state": "failed",
        "error": {"code": "media.probe_failed", "message": "x", "retryable": False},
        "started_at": NOW,
        "finished_at": NOW,
    }
    with transaction(conn):
        repo.save(load("job", failed))  # type: ignore[arg-type]
    assert repo.get(queued.id).state == "failed"
    assert repo.list_unfinished() == []


def test_sessions_and_membership(conn: sqlite3.Connection) -> None:
    _seed(conn)
    sessions = SessionRepository(conn)
    link = SessionAsset(session_id=SESSION_ID, asset_id=ASSET_ID, order_index=0, session_start_ms=0)
    with transaction(conn):
        sessions.add_asset(link)
    assert sessions.get(SESSION_ID) == _session()
    assert sessions.all() == [_session()]
    assert sessions.assets(SESSION_ID) == [link]
    assert AssetRepository(conn).original_path(ASSET_ID) == "/captures/a.mp4"


def test_settings_round_trip_json(conn: sqlite3.Connection) -> None:
    settings = SettingsRepository(conn)
    assert settings.get("import.mode", "reference") == "reference"
    with transaction(conn):
        settings.set("import.mode", "managed")
        settings.set("ui.recent", [1, 2.5, None, {"a": True}])
    assert settings.get("import.mode") == "managed"
    assert settings.all() == {"import.mode": "managed", "ui.recent": [1, 2.5, None, {"a": True}]}


def test_mark_missing_keeps_the_asset(conn: sqlite3.Connection) -> None:
    _seed(conn)
    repo = AssetRepository(conn)
    with transaction(conn):
        repo.mark_missing(ASSET_ID, NOW)
    assert repo.get(ASSET_ID).missing_at == NOW


def test_missing_rows_raise_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        AssetRepository(conn).get(ASSET_ID)
    with pytest.raises(NotFoundError):
        SessionRepository(conn).delete(SESSION_ID)
    with pytest.raises(NotFoundError):
        EventRepository(conn).set_review_state("evt_01JCBQ00000000000000000003", "confirmed")


# -- delete policies ------------------------------------------------------------------


def test_asset_in_a_session_cannot_be_deleted(conn: sqlite3.Connection) -> None:
    _seed(conn)
    sessions = SessionRepository(conn)
    with transaction(conn):
        sessions.add_asset(
            SessionAsset(
                session_id=SESSION_ID, asset_id=ASSET_ID, order_index=0, session_start_ms=0
            )
        )
    with pytest.raises(InUseError), transaction(conn):
        AssetRepository(conn).delete(ASSET_ID)
    assert sessions.assets(SESSION_ID)  # membership untouched

    with transaction(conn):
        sessions.remove_asset(SESSION_ID, ASSET_ID)
        AssetRepository(conn).delete(ASSET_ID)
    with pytest.raises(NotFoundError):
        AssetRepository(conn).get(ASSET_ID)


def test_asset_referenced_by_an_event_cannot_be_deleted(conn: sqlite3.Connection) -> None:
    _seed(conn)
    raw = read_json(contract_fixtures("event")[0])
    with transaction(conn):
        EventRepository(conn).add(load("event", raw))  # type: ignore[arg-type]
    with pytest.raises(InUseError), transaction(conn):
        AssetRepository(conn).delete(ASSET_ID)
    assert EventRepository(conn).get(raw["id"])


def test_deleting_a_session_cascades_derived_rows_only(conn: sqlite3.Connection) -> None:
    _seed(conn)
    event: Event = load("event", read_json(contract_fixtures("event")[0]))  # type: ignore[assignment]
    with transaction(conn):
        SessionRepository(conn).add_asset(
            SessionAsset(
                session_id=SESSION_ID, asset_id=ASSET_ID, order_index=0, session_start_ms=0
            )
        )
        EventRepository(conn).add(event)
        conn.execute(
            "INSERT INTO transcript_segments (session_id, start_ms, end_ms, text) "
            "VALUES (?, 0, 10, 'hi')",
            (SESSION_ID,),
        )
    with transaction(conn):
        SessionRepository(conn).delete(SESSION_ID)
    for table in ("session_assets", "events", "transcript_segments"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table  # noqa: S608
    assert AssetRepository(conn).get(ASSET_ID)  # the source asset survives


def test_session_with_a_story_cannot_be_deleted(conn: sqlite3.Connection) -> None:
    _seed(conn)
    story = _story(read_json(contract_fixtures("project")[-1]))
    with transaction(conn):
        StoryRepository(conn).save(story)
    with pytest.raises(InUseError), transaction(conn):
        SessionRepository(conn).delete(SESSION_ID)
    with transaction(conn):
        StoryRepository(conn).delete(story.id)
        SessionRepository(conn).delete(SESSION_ID)


# -- constraints and transactions ----------------------------------------------------


def test_duplicate_content_hash_is_rejected(conn: sqlite3.Connection) -> None:
    _seed(conn)
    with pytest.raises(ConflictError), transaction(conn):
        AssetRepository(conn).add(_asset(OTHER_ASSET_ID))
    found = AssetRepository(conn).find_by_sha256("3f" * 32)
    assert found is not None and found.id == ASSET_ID


def test_session_order_is_unique(conn: sqlite3.Connection) -> None:
    _seed(conn)
    sessions = SessionRepository(conn)
    with transaction(conn):
        AssetRepository(conn).add(_asset(OTHER_ASSET_ID, "4e" * 32))
        sessions.add_asset(
            SessionAsset(
                session_id=SESSION_ID, asset_id=ASSET_ID, order_index=0, session_start_ms=0
            )
        )
    with pytest.raises(ConflictError), transaction(conn):
        sessions.add_asset(
            SessionAsset(
                session_id=SESSION_ID, asset_id=OTHER_ASSET_ID, order_index=0, session_start_ms=5
            )
        )


def test_membership_requires_existing_rows(conn: sqlite3.Connection) -> None:
    with pytest.raises(ConflictError), transaction(conn):
        SessionRepository(conn).add_asset(
            SessionAsset(
                session_id=SESSION_ID, asset_id=ASSET_ID, order_index=0, session_start_ms=0
            )
        )


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (
            INSERT_SESSION.format(state="unreviewed"),
            ("ses_bad", NOW),
        ),
        (
            INSERT_SESSION.format(state="unreviewed"),
            (ASSET_ID, NOW),
        ),
        (
            INSERT_SESSION.format(state="maybe"),
            (SESSION_ID, NOW),
        ),
        (
            "INSERT INTO jobs (id, kind, state, created_at) "
            "VALUES ('job_01JCBQ00000000000000000004', 'import', 'failed', ?)",
            (NOW,),
        ),
        ("INSERT INTO settings (key, value_json, updated_at) VALUES ('', '1', ?)", (NOW,)),
    ],
    ids=["short-id", "wrong-prefix", "bad-enum", "failed-job-without-error", "empty-setting-key"],
)
def test_schema_checks_reject_bad_rows(
    conn: sqlite3.Connection, sql: str, params: tuple[str, ...]
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, params)


def test_transaction_rolls_back_every_write(conn: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), transaction(conn):
        AssetRepository(conn).add(_asset())
        SessionRepository(conn).add(_session())
        raise RuntimeError("boom")
    assert AssetRepository(conn).all() == []
    assert SessionRepository(conn).all() == []


def test_failed_write_rolls_back_earlier_writes_in_the_transaction(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(ConflictError), transaction(conn):
        AssetRepository(conn).add(_asset())
        AssetRepository(conn).add(_asset(OTHER_ASSET_ID))  # same sha256
    assert AssetRepository(conn).all() == []


def test_story_id_must_match_timeline(conn: sqlite3.Connection) -> None:
    story = _story(read_json(contract_fixtures("project")[-1]))
    mismatched = story.model_copy(update={"id": "prj_01JCBQ00000000000000000077"})
    with pytest.raises(ConflictError):
        StoryRepository(conn).save(mismatched)
    assert story.id == PROJECT_ID
