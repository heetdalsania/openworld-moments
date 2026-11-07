# SPDX-License-Identifier: AGPL-3.0-or-later
"""Append-only decisions over immutable event snapshots; never match new IDs silently."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from typing import Any, Literal

from openworld_moments_contracts import load, normalize
from pydantic import BaseModel, ConfigDict, Field, model_validator

from openworld_moments.detectors.profiles import canonical, digest
from openworld_moments.ids import new_id
from openworld_moments.storage import (
    Database,
    EventRepository,
    SessionRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

EVENT_TYPE = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
SHA = r"^[a-f0-9]{64}$"


class ReviewError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class ReviewChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    layout_key: str = Field(pattern=SHA)
    expected_revision: int = Field(ge=0)
    action: Literal["approve", "reject", "correct", "reset"]
    type: str | None = Field(default=None, pattern=EVENT_TYPE, max_length=128)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def correction_fields(self) -> ReviewChange:
        fields = (self.type, self.start_ms, self.end_ms)
        if self.action == "correct":
            if any(v is None for v in fields):
                raise ValueError("A correction needs a type and both interval boundaries.")
        elif any(v is not None for v in fields):
            raise ValueError("Only a correction accepts label and interval fields.")
        return self


class ManualEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    layout_key: str = Field(pattern=SHA)
    type: str = Field(pattern=EVENT_TYPE, max_length=128)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


def layout_info(conn: sqlite3.Connection, sid: str) -> tuple[str, int]:
    SessionRepository(conn).get(sid)
    rows = [
        tuple(r)
        for r in conn.execute(
            "SELECT sa.asset_id,a.duration_ms,sa.overlap_with_previous_ms FROM session_assets sa "
            "JOIN media_assets a ON a.id=sa.asset_id WHERE sa.session_id=? ORDER BY sa.order_index",
            (sid,),
        )
    ]
    duration = sum(
        max(0, duration - (hidden if i else 0)) for i, (_, duration, hidden) in enumerate(rows)
    )
    return digest(rows), duration


def snapshot(conn: sqlite3.Connection, doc: dict[str, Any], key: str | None) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO event_observations VALUES(?,?,?,?,?)",
        (doc["id"], doc["session_id"], canonical(doc), key, utc_now()),
    )


class EventReviewService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _legacy(conn: sqlite3.Connection, sid: str) -> None:
        # Existing output has no proven layout key. Preserve it for inspection,
        # but refuse review until it is rerun against the current layout.
        for row in conn.execute(
            "SELECT id FROM events WHERE session_id=? AND id NOT IN "
            "(SELECT event_id FROM event_observations WHERE session_id=?)",
            (sid, sid),
        ).fetchall():
            snapshot(conn, normalize(EventRepository(conn).get(row[0])), None)

    @staticmethod
    def _item(conn: sqlite3.Connection, sid: str, eid: str, key: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT original_json,layout_key FROM event_observations "
            "WHERE event_id=? AND session_id=?",
            (eid, sid),
        ).fetchone()
        if row is None:
            raise ReviewError("review.not_found", "That event is not in this session.", 404)
        original = json.loads(row[0])
        decisions = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT decision_json FROM event_decisions WHERE event_id=? "
                "ORDER BY revision DESC LIMIT 20",
                (eid,),
            )
        ][::-1]
        effective = json.loads(row[0])
        if decisions:
            last = decisions[-1]
            effective.update(
                type=last["type"],
                start_ms=last["start_ms"],
                end_ms=last["end_ms"],
                review_state=last["state"],
            )
        active = conn.execute(
            "SELECT 1 FROM events WHERE id=? AND session_id=?", (eid, sid)
        ).fetchone()
        status = (
            "superseded"
            if not active
            else "legacy"
            if row[1] is None
            else "stale"
            if row[1] != key
            else "current"
        )
        return {
            "original": original,
            "effective": effective,
            "revision": decisions[-1]["revision"] if decisions else 0,
            "status": status,
            "history": decisions,
            "history_truncated": bool(decisions and decisions[0]["revision"] > 1),
        }

    def page(self, sid: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        offset, limit = max(0, offset), max(1, min(100, limit))
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            key, duration = layout_info(conn, sid)
            self._legacy(conn, sid)
            # Current candidates plus reviewed history. Superseded unreviewed
            # snapshots remain archived, without flooding the review screen.
            query = (
                "FROM event_observations o WHERE o.session_id=? AND (EXISTS "
                "(SELECT 1 FROM events e WHERE e.id=o.event_id) OR EXISTS "
                "(SELECT 1 FROM event_decisions d WHERE d.event_id=o.event_id))"
            )
            total = conn.execute("SELECT count(*) " + query, (sid,)).fetchone()[0]
            ids = conn.execute(
                "SELECT o.event_id " + query + " ORDER BY o.created_at,o.event_id LIMIT ? OFFSET ?",
                (sid, limit, offset),
            ).fetchall()
            result = {
                "schema_version": SCHEMA_VERSION,
                "session_id": sid,
                "layout_key": key,
                "duration_ms": duration,
                "offset": offset,
                "total": total,
                "items": [self._item(conn, sid, r[0], key) for r in ids],
            }
        return normalize(load("event-review", result))

    @staticmethod
    def _check_layout(key: str, expected: str) -> None:
        if key != expected:
            raise ReviewError(
                "review.session_changed", "The session changed. Refresh before reviewing."
            )

    @staticmethod
    def _interval(start: int, end: int, duration: int) -> None:
        if not 0 <= start < end <= duration:
            raise ReviewError(
                "review.invalid_interval",
                "Choose an interval inside the session with end after start.",
                422,
            )

    def change(self, sid: str, eid: str, change: ReviewChange) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            key, duration = layout_info(conn, sid)
            self._check_layout(key, change.layout_key)
            self._legacy(conn, sid)
            item = self._item(conn, sid, eid, key)
            if item["status"] != "current":
                raise ReviewError(
                    "review.obsolete",
                    "This observation is historical or has stale timing. "
                    "Re-analyze, then review its replacement.",
                )
            if item["revision"] != change.expected_revision:
                raise ReviewError(
                    "review.conflict", "Another review changed this event. Refresh and try again."
                )
            effective = item["original"] if change.action == "reset" else item["effective"]
            state = {
                "approve": "confirmed",
                "reject": "rejected",
                "correct": "corrected",
                "reset": "unreviewed",
            }[change.action]
            if change.action == "correct":
                effective = {
                    **effective,
                    "type": change.type,
                    "start_ms": change.start_ms,
                    "end_ms": change.end_ms,
                }
                self._interval(effective["start_ms"], effective["end_ms"], duration)
            decision = {
                "revision": item["revision"] + 1,
                "state": state,
                "type": effective["type"],
                "start_ms": effective["start_ms"],
                "end_ms": effective["end_ms"],
                "created_at": utc_now(),
            }
            conn.execute(
                "INSERT INTO event_decisions VALUES(?,?,?)",
                (eid, decision["revision"], canonical(decision)),
            )
            return self._item(conn, sid, eid, key)

    def manual(self, sid: str, event: ManualEvent) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            key, duration = layout_info(conn, sid)
            self._check_layout(key, event.layout_key)
            self._interval(event.start_ms, event.end_ms, duration)
            doc: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "id": new_id("evt"),
                "session_id": sid,
                "type": event.type,
                "start_ms": event.start_ms,
                "end_ms": event.end_ms,
                "confidence": 1,
                "attributes": {},
                "evidence": [],
                "source": {"kind": "user"},
                "review_state": "confirmed",
            }
            EventRepository(conn).add(load("event", doc))  # type: ignore[arg-type]
            snapshot(conn, doc, key)
            return self._item(conn, sid, doc["id"], key)
