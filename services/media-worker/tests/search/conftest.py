# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small library written through the canonical tables (the triggers index it)."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.search.service import SearchService
from openworld_moments.storage import Database, transaction

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(prefix: str, n: int) -> str:
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[n & 31])
        n >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


class Library:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.service = SearchService(database)
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    def sql(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            conn.execute(statement, params)

    def session(self, title: str = "Evening session", started_at: str | None = None) -> str:
        sid = ulid("ses", self._next())
        self.sql(
            "INSERT INTO sessions (id, title, started_at, review_state, created_at) "
            "VALUES (?, ?, ?, 'unreviewed', '2026-11-20T00:00:00Z')",
            (sid, title, started_at or "2026-11-20T10:00:00Z"),
        )
        return sid

    def clip(
        self,
        session_id: str | None = None,
        name: str = "Capture.mp4",
        *,
        duration_ms: int = 30_000,
        source_kind: str = "xbox",
        captured_at: str = "2026-11-20T10:00:00Z",
        order: int = 0,
    ) -> str:
        aid = ulid("ast", self._next())
        self.sql(
            "INSERT INTO media_assets (id, sha256, original_name, source_kind, import_mode, "
            "duration_ms, container, created_at, captured_at, captured_at_confidence, "
            "captured_at_basis_json) VALUES (?, ?, ?, ?, 'reference', ?, 'mp4', "
            "'2026-11-20T00:00:00Z', ?, 0.9, '[\"filename\"]')",
            (
                aid,
                hashlib.sha256(aid.encode()).hexdigest(),
                name,
                source_kind,
                duration_ms,
                captured_at,
            ),
        )
        if session_id:
            self.sql(
                "INSERT INTO session_assets (session_id, asset_id, order_index, session_start_ms) "
                "VALUES (?, ?, ?, 0)",
                (session_id, aid, order),
            )
        return aid

    def event(
        self,
        session_id: str,
        asset_id: str | None,
        type_: str = "openworld.wanted_level_changed",
        *,
        start_ms: int = 1000,
        end_ms: int = 2000,
        confidence: float = 0.9,
        text: str | None = None,
        review_state: str = "unreviewed",
    ) -> str:
        eid = ulid("evt", self._next())
        attributes = {"text": text} if text is not None else {}
        self.sql(
            "INSERT INTO events (id, session_id, asset_id, type, start_ms, end_ms, confidence, "
            "attributes_json, evidence_json, source_kind, detector_id, detector_version, "
            "review_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', 'detector', 'test', '1.0.0', ?)",
            (
                eid,
                session_id,
                asset_id,
                type_,
                start_ms,
                end_ms,
                confidence,
                json.dumps(attributes),
                review_state,
            ),
        )
        self.sql(
            "INSERT INTO event_observations VALUES (?, ?, '{}', NULL, '2026-11-20T00:00:00Z')",
            (eid, session_id),
        )
        return eid

    def decide(self, event_id: str, state: str, revision: int = 1, **overrides: Any) -> None:
        with contextlib.closing(self.database.connect()) as conn:
            row = conn.execute(
                "SELECT type, start_ms, end_ms FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        decision = {
            "revision": revision,
            "state": state,
            "type": overrides.get("type", row["type"]),
            "start_ms": overrides.get("start_ms", row["start_ms"]),
            "end_ms": overrides.get("end_ms", row["end_ms"]),
            "created_at": "2026-11-21T00:00:00Z",
        }
        self.sql(
            "INSERT INTO event_decisions VALUES (?, ?, ?)",
            (event_id, revision, json.dumps(decision)),
        )

    def span(
        self,
        session_id: str,
        asset_id: str | None,
        text: str,
        *,
        start_ms: int = 1000,
        end_ms: int = 2000,
        speaker: str | None = None,
        confidence: float = 0.9,
    ) -> int:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            cursor = conn.execute(
                "INSERT INTO transcript_segments (session_id, start_ms, end_ms, speaker, text, "
                "language, confidence, asset_id, source_start_ms, source_end_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'en', ?, ?, ?, ?, '2026-11-21T00:00:00Z')",
                (
                    session_id,
                    start_ms,
                    end_ms,
                    speaker,
                    text,
                    confidence,
                    asset_id,
                    start_ms + 500,
                    end_ms + 500,
                ),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def project(self, session_id: str | None, title: str) -> str:
        pid = ulid("prj", self._next())
        self.sql(
            "INSERT INTO stories (id, session_id, title, timeline_json, review_state, created_at, "
            "updated_at) VALUES (?, ?, ?, '{}', 'accepted', '2026-11-21T00:00:00Z', "
            "'2026-11-21T00:00:00Z')",
            (pid, session_id, title),
        )
        return pid

    def search(self, query: str = "", **filters: Any) -> dict[str, Any]:
        from openworld_moments.search.filters import SearchFilters, SearchRequest

        limit = filters.pop("limit", 25)
        offset = filters.pop("offset", 0)
        return self.service.search(
            SearchRequest(
                query=query,
                filters=SearchFilters.model_validate(filters),
                limit=limit,
                offset=offset,
            )
        )

    def keys(self, query: str = "", **filters: Any) -> list[str]:
        return [item["key"] for item in self.search(query, **filters)["items"]]


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "library.sqlite3")


@pytest.fixture
def lib(database: Database) -> Iterator[Library]:
    yield Library(database)
