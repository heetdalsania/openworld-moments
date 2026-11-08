# SPDX-License-Identifier: AGPL-3.0-or-later
"""Index maintenance: rebuild, stale and corrupt detection, cancellation, clearing."""

from __future__ import annotations

import contextlib
import hashlib
import threading
from typing import Any

import pytest

from openworld_moments.search import index
from openworld_moments.search.service import SearchError
from openworld_moments.storage import Database, transaction
from openworld_moments.storage.database import bundled_migrations
from tests.search.conftest import Library

CANONICAL = (
    "media_assets",
    "sessions",
    "session_assets",
    "events",
    "event_observations",
    "event_decisions",
    "transcript_segments",
    "stories",
    "collections",
    "collection_items",
)


def fingerprint(database: Database) -> str:
    digest = hashlib.sha256()
    with contextlib.closing(database.connect()) as conn:
        for table in CANONICAL:
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):  # noqa: S608
                digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


def populated(lib: Library, sessions: int = 3) -> None:
    for s in range(sessions):
        sid = lib.session(f"Session {s}")
        aid = lib.clip(sid, f"clip {s}.mp4")
        for e in range(4):
            eid = lib.event(sid, aid, text=f"banner {s} {e}")
            if e % 2:
                lib.decide(eid, "confirmed")
        for t in range(3):
            lib.span(sid, aid, f"line {s} {t} getaway")
        lib.project(sid, f"Project {s}")


def corrupt_full_text(database: Database) -> None:
    with contextlib.closing(database.connect()) as conn, transaction(conn):
        conn.execute("UPDATE search_fts_data SET block = zeroblob(length(block)) WHERE id > 10")


def test_index_version_default_matches_the_code() -> None:
    latest = bundled_migrations()[-1].sql
    assert f"index_version    INTEGER NOT NULL DEFAULT {index.INDEX_VERSION}" in latest


def test_triggers_keep_the_index_current(lib: Library) -> None:
    populated(lib)
    status = index.status(lib.database, check=True)
    assert status["status"] == "current" and status["reasons"] == []
    assert status["documents"] == {
        "clip": 3,
        "session": 3,
        "event": 12,
        "transcript": 9,
        "project": 3,
    }


def test_rebuild_never_changes_canonical_records(lib: Library) -> None:
    populated(lib)
    before = fingerprint(lib.database)
    progress: list[tuple[int, int, str]] = []
    result = index.rebuild(lib.database, progress=lambda d, t, m: progress.append((d, t, m)))
    assert result == {"documents": 30}
    assert fingerprint(lib.database) == before
    assert progress[0] == (0, 30, "Indexing") and progress[-1] == (30, 30, "Verifying")
    assert [p[0] for p in progress] == sorted(p[0] for p in progress)
    assert index.status(lib.database, check=True)["status"] == "current"


def test_stale_documents_are_detected_and_repaired(lib: Library) -> None:
    populated(lib)
    with contextlib.closing(lib.database.connect()) as conn, transaction(conn):
        conn.execute("DELETE FROM search_documents WHERE kind = 'transcript' AND transcript_id = 1")
    light = index.status(lib.database)
    assert light["status"] == "stale" and light["reasons"] == ["documents_out_of_date"]
    index.rebuild(lib.database)
    assert index.status(lib.database, check=True)["status"] == "current"
    # Content drift with equal counts is only found by the full check.
    with contextlib.closing(lib.database.connect()) as conn, transaction(conn):
        conn.execute("UPDATE search_documents SET start_ms = 99999 WHERE kind = 'event'")
    assert index.status(lib.database)["status"] == "current"
    assert index.status(lib.database, check=True)["reasons"] == ["documents_out_of_date"]
    index.rebuild(lib.database)
    assert index.status(lib.database, check=True)["status"] == "current"


def test_an_old_index_version_is_stale_until_rebuilt(lib: Library) -> None:
    populated(lib, 1)
    with contextlib.closing(lib.database.connect()) as conn, transaction(conn):
        conn.execute("UPDATE search_index_state SET index_version = 2")
        conn.execute("UPDATE search_documents SET index_version = 0 WHERE kind = 'project'")
    status = index.status(lib.database)
    assert status["status"] == "stale" and "version_changed" in status["reasons"]
    assert lib.search("getaway")["index_status"] == "stale"
    index.rebuild(lib.database)
    with contextlib.closing(lib.database.connect()) as conn:
        versions = {
            r[0] for r in conn.execute("SELECT DISTINCT index_version FROM search_documents")
        }
    assert versions == {index.INDEX_VERSION}
    assert index.status(lib.database)["status"] == "current"


def test_a_corrupt_full_text_index_fails_safely_and_rebuilds(lib: Library) -> None:
    populated(lib)
    before = fingerprint(lib.database)
    corrupt_full_text(lib.database)
    status = index.status(lib.database, check=True)
    assert status["status"] == "corrupt" and "full_text_corrupt" in status["reasons"]
    with pytest.raises(SearchError) as caught:
        lib.search("getaway")
    assert caught.value.code == "search.index_unavailable" and caught.value.status == 503
    index.rebuild(lib.database)
    assert index.status(lib.database, check=True)["status"] == "current"
    assert lib.search("getaway")["total"] == 9
    assert fingerprint(lib.database) == before


def test_a_dropped_full_text_table_is_recreated(lib: Library) -> None:
    populated(lib, 1)
    with contextlib.closing(lib.database.connect()) as conn, transaction(conn):
        conn.execute("DROP TABLE search_fts")
    with pytest.raises(SearchError):
        lib.search("getaway")
    assert index.status(lib.database, check=True)["status"] == "corrupt"
    index.rebuild(lib.database)
    assert lib.search("getaway")["total"] == 3
    with contextlib.closing(lib.database.connect()) as conn:
        secure = conn.execute(
            "SELECT v FROM search_fts_config WHERE k = 'secure-delete'"
        ).fetchone()
    assert secure is not None and secure[0] == 1


def test_cancelled_rebuild_keeps_a_usable_index_marked_incomplete(
    lib: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    populated(lib, 3)
    monkeypatch.setattr(index, "BATCH", 2)
    cancel = threading.Event()
    seen: list[int] = []

    def progress(done: int, total: int, message: str) -> None:
        seen.append(done)
        if done >= 4:
            cancel.set()

    with pytest.raises(index.IndexCancelled):
        index.rebuild(lib.database, cancel=cancel, progress=progress)
    assert max(seen) < 30
    status = index.status(lib.database)
    assert status["status"] == "rebuilding" and status["reasons"] == ["rebuild_incomplete"]
    assert lib.search("getaway")["total"] == 9  # still searchable
    assert lib.search("getaway")["index_status"] == "rebuilding"
    index.rebuild(lib.database)
    assert index.status(lib.database, check=True)["status"] == "current"


def test_clear_deletes_derived_text_only(lib: Library) -> None:
    populated(lib, 2)
    before = fingerprint(lib.database)
    index.clear(lib.database)
    assert fingerprint(lib.database) == before
    status = index.status(lib.database)
    assert status["status"] == "cleared" and set(status["documents"].values()) == {0}
    assert lib.search("getaway")["total"] == 0
    assert lib.search("getaway")["index_status"] == "cleared"
    with contextlib.closing(lib.database.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM search_fts_idx").fetchone()[0] <= 1
        assert index.fts_healthy(conn)
    # Later changes are indexed again; the index stays marked incomplete.
    sid = lib.session("After clearing")
    assert lib.keys("clearing") == [f"session:{sid}"]
    assert index.status(lib.database)["status"] == "cleared"
    index.rebuild(lib.database)
    assert index.status(lib.database, check=True)["status"] == "current"
    assert lib.search("getaway")["total"] == 6


def test_migration_builds_the_index_for_an_existing_library(tmp_path: Any) -> None:
    migrations = bundled_migrations()
    old = Database(tmp_path / "old.sqlite3", migrations=migrations[:15])
    old.migrate()
    with contextlib.closing(old.connect()) as conn, transaction(conn):
        conn.execute(
            "INSERT INTO sessions (id, title, review_state, created_at) "
            "VALUES ('ses_01JCBQ00000000000000000002', 'Legacy heist', 'unreviewed', "
            "'2026-11-20T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO collections (id, name, created_at) VALUES (7, 'Old picks', "
            "'2026-11-20T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO collection_items (collection_id, session_id, position, added_at) "
            "VALUES (7, 'ses_01JCBQ00000000000000000002', 0, '2026-11-20T00:00:00Z')"
        )
    upgraded = Database(tmp_path / "old.sqlite3")
    upgraded.migrate()
    library = Library(upgraded)
    assert library.keys("heist") == ["session:ses_01JCBQ00000000000000000002"]
    assert index.status(upgraded, check=True)["status"] == "current"
    collection = library.service.collection("col_00000000000000000000000007")
    assert collection["name"] == "Old picks" and collection["kind"] == "manual"
    assert [i["key"] for i in collection["items"]] == ["session:ses_01JCBQ00000000000000000002"]
