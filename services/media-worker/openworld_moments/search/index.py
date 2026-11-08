# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search index maintenance (M26): status, stale/corrupt detection, rebuild, clear.

The index is derived. Triggers keep it current in the same transaction as canonical
changes (migration 0016); this module only verifies it and rebuilds it from the
``search_source_*`` views. Nothing here writes a canonical table or touches media.

Rebuild works in small transactions, so the library stays usable and a cancelled
rebuild leaves a valid (if partly refreshed) index marked for another rebuild:

1. If the full-text index fails its integrity check, rebuild it from the stored
   documents first (recreating the FTS table if SQLite cannot repair it).
2. Per kind, upsert documents in batches of canonical IDs from the views; an
   unchanged title and body leave the full-text index alone.
3. Remove documents whose canonical row is gone or whose index version is old.
4. Rebuild and optimize the full-text index, verify it, and mark it current.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openworld_moments.storage import Database, transaction, utc_now

#: Must match the search_documents.index_version default in the latest migration.
INDEX_VERSION = 1
BATCH = 500

COLUMNS = (
    "doc_key, kind, session_id, asset_id, event_id, transcript_id, project_id, title, body, "
    "start_ms, end_ms, source_start_ms, source_end_ms, occurred_at, duration_ms, source_kind, "
    "event_type, confidence, review_state"
)
#: Upsert assignments: replace every column, keeping the row (and full-text rowid).
UPSERT = ", ".join(f"{c} = excluded.{c}" for c in [*COLUMNS.split(", ")[1:], "index_version"])
FTS_CREATE = (
    "CREATE VIRTUAL TABLE search_fts USING fts5(title, body, content = 'search_documents', "
    "content_rowid = 'id', tokenize = 'unicode61 remove_diacritics 2')"
)


@dataclass(frozen=True, slots=True)
class Source:
    kind: str
    view: str
    key: str  # ID column in the view and in search_documents
    table: str  # canonical table, for cheap counts


SOURCES = (
    Source("clip", "search_source_clips", "asset_id", "media_assets"),
    Source("session", "search_source_sessions", "session_id", "sessions"),
    Source("event", "search_source_events", "event_id", "events"),
    Source("transcript", "search_source_transcripts", "transcript_id", "transcript_segments"),
    Source("project", "search_source_projects", "project_id", "stories"),
)

Progress = Callable[[int, int, str], None]


class IndexCancelled(Exception):
    pass


def fts_healthy(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("INSERT INTO search_fts (search_fts, rank) VALUES ('integrity-check', 1)")
    except sqlite3.DatabaseError:
        return False
    return True


def _state(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT index_version, status, built_at FROM search_index_state WHERE id = 1"
    ).fetchone()
    if row is None:  # pragma: no cover - created by migration 0016
        return {"index_version": 0, "status": "cleared", "built_at": None}
    return dict(row)


def status(database: Database, *, check: bool = False) -> dict[str, Any]:
    """Index status. ``check`` also compares every document with its source view and
    runs the full-text integrity check (slower; the light form only compares counts).
    """
    with contextlib.closing(database.connect()) as conn:
        state = _state(conn)
        counts = {s.kind: 0 for s in SOURCES}
        for kind, count in conn.execute(
            "SELECT kind, count(*) FROM search_documents GROUP BY kind"
        ):
            counts[kind] = count
        reasons: list[str] = []
        if state["index_version"] != INDEX_VERSION:
            reasons.append("version_changed")
        if state["status"] == "rebuilding":
            reasons.append("rebuild_incomplete")
        if state["status"] == "cleared":
            reasons.append("cleared")
        expected = {
            s.kind: conn.execute(f"SELECT count(*) FROM {s.table}").fetchone()[0]  # noqa: S608
            for s in SOURCES
        }
        if expected != counts:
            reasons.append("documents_out_of_date")
        corrupt = False
        if check:
            if "documents_out_of_date" not in reasons and _differs(conn):
                reasons.append("documents_out_of_date")
            corrupt = not fts_healthy(conn)
            if corrupt:
                reasons.append("full_text_corrupt")
        overall = (
            "corrupt"
            if corrupt
            else "rebuilding"
            if state["status"] == "rebuilding"
            else "cleared"
            if state["status"] == "cleared"
            else "stale"
            if reasons
            else "current"
        )
        result: dict[str, Any] = {
            "index_version": state["index_version"],
            "expected_version": INDEX_VERSION,
            "status": overall,
            "reasons": reasons,
            "documents": counts,
            "checked": check,
        }
        if state["built_at"]:
            result["built_at"] = state["built_at"]
        return result


def _differs(conn: sqlite3.Connection) -> bool:
    for source in SOURCES:
        for query in (
            f"SELECT {COLUMNS} FROM {source.view} EXCEPT "  # noqa: S608
            f"SELECT {COLUMNS} FROM search_documents WHERE kind = ?",
            f"SELECT {COLUMNS} FROM search_documents WHERE kind = ? EXCEPT "  # noqa: S608
            f"SELECT {COLUMNS} FROM {source.view}",
        ):
            if conn.execute(f"SELECT EXISTS ({query})", (source.kind,)).fetchone()[0]:
                return True
    return False


def _set_state(conn: sqlite3.Connection, status_value: str, *, built: bool = False) -> None:
    now = utc_now()
    if built:
        conn.execute(
            "UPDATE search_index_state SET status = ?, updated_at = ?, index_version = ?, "
            "built_at = ? WHERE id = 1",
            (status_value, now, INDEX_VERSION, now),
        )
    else:
        conn.execute(
            "UPDATE search_index_state SET status = ?, updated_at = ? WHERE id = 1",
            (status_value, now),
        )


def _repair_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the full-text index from search_documents, recreating it if needed."""
    with transaction(conn):
        try:
            conn.execute("INSERT INTO search_fts (search_fts) VALUES ('rebuild')")
            return
        except sqlite3.DatabaseError:
            pass
    with transaction(conn):
        conn.execute("DROP TABLE IF EXISTS search_fts")
        conn.execute(FTS_CREATE)
        conn.execute("INSERT INTO search_fts (search_fts, rank) VALUES ('secure-delete', 1)")
        conn.execute("INSERT INTO search_fts (search_fts) VALUES ('rebuild')")


def rebuild(
    database: Database,
    *,
    cancel: threading.Event | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Rebuild every document from the source views. Raises :class:`IndexCancelled`."""
    cancel = cancel or threading.Event()

    def report(done: int, total: int, message: str) -> None:
        if progress is not None:
            progress(min(done, total), max(total, 1), message)

    with contextlib.closing(database.connect()) as conn:
        conn.execute("PRAGMA secure_delete = ON")
        with transaction(conn):
            _set_state(conn, "rebuilding")
        if not fts_healthy(conn):
            _repair_fts(conn)
        total = sum(
            conn.execute(f"SELECT count(*) FROM {s.view}").fetchone()[0]  # noqa: S608
            for s in SOURCES
        )
        done = 0
        report(0, total, "Indexing")
        for source in SOURCES:
            last: Any = None
            while True:
                if cancel.is_set():
                    raise IndexCancelled
                if last is None:
                    rows = conn.execute(
                        f"SELECT {source.key} FROM {source.view} "  # noqa: S608
                        f"ORDER BY {source.key} LIMIT ?",
                        (BATCH,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT {source.key} FROM {source.view} "  # noqa: S608
                        f"WHERE {source.key} > ? ORDER BY {source.key} LIMIT ?",
                        (last, BATCH),
                    ).fetchall()
                if not rows:
                    break
                keys = [r[0] for r in rows]
                marks = ",".join("?" * len(keys))
                with transaction(conn):
                    conn.execute(
                        f"INSERT INTO search_documents ({COLUMNS}) "  # noqa: S608
                        f"SELECT {COLUMNS} FROM {source.view} WHERE {source.key} IN ({marks}) "
                        f"ON CONFLICT (doc_key) DO UPDATE SET {UPSERT}",
                        keys,
                    )
                done += len(keys)
                last = keys[-1]
                report(done, total, "Indexing")
        if cancel.is_set():
            raise IndexCancelled
        report(total, total, "Verifying")
        with transaction(conn):
            for source in SOURCES:
                conn.execute(
                    f"DELETE FROM search_documents WHERE kind = ? AND ("  # noqa: S608
                    f"{source.key} IS NULL OR {source.key} NOT IN "
                    f"(SELECT {source.key} FROM {source.view}))",
                    (source.kind,),
                )
            conn.execute("DELETE FROM search_documents WHERE index_version <> ?", (INDEX_VERSION,))
        _repair_fts(conn)
        with transaction(conn):
            conn.execute("INSERT INTO search_fts (search_fts) VALUES ('optimize')")
        if not fts_healthy(conn):  # pragma: no cover - repaired above
            raise sqlite3.DatabaseError("the rebuilt full-text index failed its check")
        with transaction(conn):
            _set_state(conn, "current", built=True)
        documents = conn.execute("SELECT count(*) FROM search_documents").fetchone()[0]
    return {"documents": documents}


def clear(database: Database) -> None:
    """Delete all derived search data (documents and full-text index).

    Canonical clips, sessions, events and transcripts are untouched. Freed pages are
    zeroed (secure_delete) and the write-ahead log is truncated afterwards. Changes
    made later are indexed again by the triggers; the index stays marked ``cleared``
    (incomplete) until it is rebuilt.
    """
    with contextlib.closing(database.connect()) as conn:
        conn.execute("PRAGMA secure_delete = ON")
        if not fts_healthy(conn):
            _repair_fts(conn)
        with transaction(conn):
            conn.execute("DELETE FROM search_documents")
            _set_state(conn, "cleared")
        _repair_fts(conn)
        with transaction(conn):
            conn.execute("INSERT INTO search_fts (search_fts) VALUES ('optimize')")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
