# SPDX-License-Identifier: AGPL-3.0-or-later
"""Atomic, versioned story generation over current M19 review snapshots."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Callable
from typing import Any, Literal

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.project_schema import Project
from pydantic import BaseModel, ConfigDict, Field

from openworld_moments.detectors.profiles import canonical, digest
from openworld_moments.review.service import EventReviewService, layout_info
from openworld_moments.storage import (
    Database,
    SessionRepository,
    StoryRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import Story
from openworld_moments.stories import algorithm

MAX_EVENTS = 5000
MAX_MEMBERS = 1000
MAX_TRANSCRIPTS = 10000
MAX_WORDS = 50000
SHA = r"^[a-f0-9]{64}$"


class StoryError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class StoryCancelled(Exception):
    pass


class StoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preset: Literal["moment", "short", "extended_short", "highlight"] = "short"
    pre_roll_ms: int | None = Field(default=None, ge=0, le=60000)
    post_roll_ms: int | None = Field(default=None, ge=0, le=60000)
    merge_gap_ms: int | None = Field(default=None, ge=0, le=30000)
    avoid_spoilers: bool = False
    allow_unreviewed: bool = True
    force: bool = False

    def options(self) -> dict[str, Any]:
        _, _, pre, post, gap = algorithm.PRESETS[self.preset]
        return {
            "pre_roll_ms": self.pre_roll_ms if self.pre_roll_ms is not None else pre,
            "post_roll_ms": self.post_roll_ms if self.post_roll_ms is not None else post,
            "merge_gap_ms": self.merge_gap_ms if self.merge_gap_ms is not None else gap,
            "avoid_spoilers": self.avoid_spoilers,
            "allow_unreviewed": self.allow_unreviewed,
        }


class StoryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_key: str = Field(pattern=SHA)
    expected_revision: int = Field(ge=0)
    state: Literal["suggested", "accepted", "rejected"]


def _large() -> StoryError:
    return StoryError(
        "story.too_large",
        "This session exceeds the bounded story input size. Split it before generating.",
        422,
    )


def snapshot(
    conn: sqlite3.Connection,
    sid: str,
    request: StoryRequest,
    check: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    key, duration = layout_info(conn, sid)
    rows = conn.execute(
        "SELECT sa.asset_id,a.duration_ms,sa.overlap_with_previous_ms FROM session_assets sa "
        "JOIN media_assets a ON a.id=sa.asset_id WHERE sa.session_id=? ORDER BY sa.order_index "
        "LIMIT ?",
        (sid, MAX_MEMBERS + 1),
    ).fetchall()
    if len(rows) > MAX_MEMBERS:
        raise _large()
    members = []
    position = 0
    for i, r in enumerate(rows):
        hidden = r[2] if i else 0
        size = max(0, r[1] - hidden)
        members.append(
            {
                "asset_id": r[0],
                "start_ms": position,
                "end_ms": position + size,
                "hidden_ms": hidden,
                "duration_ms": r[1],
            }
        )
        position += size
    ids = conn.execute(
        "SELECT e.id FROM events e JOIN event_observations o ON o.event_id=e.id WHERE "
        "e.session_id=? AND o.layout_key=? ORDER BY e.start_ms,e.id LIMIT ?",
        (sid, key, MAX_EVENTS + 1),
    ).fetchall()
    if len(ids) > MAX_EVENTS:
        raise _large()
    events = []
    for row in ids:
        check()
        item = EventReviewService._item(conn, sid, row[0], key)
        if item["status"] != "current":
            continue
        e, original = item["effective"], item["original"]
        if not 0 <= e["start_ms"] < e["end_ms"] <= duration:
            continue
        attributes = e.get("attributes", {})
        source = original["source"]
        supporting = (
            source.get("detector_id") == "audio-features"
            or original["type"].startswith("openworld.audio_")
            or original["type"] in ("openworld.silence", "openworld.speech_activity")
            or any(x.get("role") == "supporting" for x in original["evidence"])
        )
        fact = {
            "event_id": e["id"],
            "revision": item["revision"],
            "type": e["type"],
            "start_ms": e["start_ms"],
            "end_ms": e["end_ms"],
            "review_state": e["review_state"],
            "confidence": e["confidence"],
            "source_kind": source["kind"],
            "supporting": supporting,
            "spoiler_risk": bool(attributes.get("spoiler_risk")),
            "observation_key": digest(original),
        }
        if e["type"] == original["type"]:
            fact.update(
                {k: attributes[k] for k in ("from", "to") if type(attributes.get(k)) is int}
            )
        events.append(fact)
    # Use source coordinates, not M18's saved session offsets, after a relayout.
    # No transcript text appears in the snapshot/candidate/report. Only a hash and
    # punctuation-derived source spans enter the input identity.
    by_asset = {m["asset_id"]: m for m in members}
    transcripts = conn.execute(
        "SELECT id,asset_id,source_start_ms,source_end_ms,text,words_json,transcriber_json "
        "FROM transcript_segments WHERE session_id=? AND transcriber_json IS NOT NULL ORDER BY "
        "asset_id,source_start_ms,id LIMIT ?",
        (sid, MAX_TRANSCRIPTS + 1),
    ).fetchall()
    if len(transcripts) > MAX_TRANSCRIPTS:
        raise _large()
    transcript_keys = []
    word_count = 0
    mapped: list[tuple[int, int, bool]] = []
    for row in transcripts:
        check()
        transcript_keys.append(digest(tuple(row)))
        m = by_asset.get(row[1])
        if m is None:
            continue
        words = json.loads(row[5] or "[]")
        word_count += len(words)
        if word_count > MAX_WORDS:
            raise _large()
        units = words or [{"source_start_ms": row[2], "source_end_ms": row[3], "text": row[4]}]
        for word in units:
            a, b = word.get("source_start_ms"), word.get("source_end_ms")
            if (
                type(a) is not int
                or type(b) is not int
                or not 0 <= a < b <= m["duration_ms"]
                or b <= m["hidden_ms"]
            ):
                continue
            a = m["start_ms"] + max(a, m["hidden_ms"]) - m["hidden_ms"]
            b = m["start_ms"] + b - m["hidden_ms"]
            terminal = (
                str(word.get("text", ""))
                .rstrip()
                .endswith((".", "?", "!", "\u3002", "\uff1f", "\uff01"))
                or not words
            )
            mapped.append((a, b, terminal))
    speech = []
    pending: tuple[int, int] | None = None
    for a, b, terminal in sorted(mapped):
        check()
        if pending and a - pending[1] > 1500:
            speech.append(pending)
            pending = None
        pending = (min(a, pending[0]) if pending else a, max(b, pending[1]) if pending else b)
        if terminal:
            speech.append(pending)
            pending = None
    if pending:
        speech.append(pending)
    combined: list[tuple[int, int]] = []
    for a, b in sorted(set(speech)):
        if combined and a < combined[-1][1]:
            combined[-1] = (combined[-1][0], max(b, combined[-1][1]))
        else:
            combined.append((a, b))
    speech = combined
    boundaries = sorted(
        set(
            (e["start_ms"] + e["end_ms"]) // 2
            if e["type"] == "openworld.silence"
            else e["start_ms"]
            for e in events
            if e["review_state"] != "rejected"
            and (
                e["review_state"] in ("confirmed", "corrected")
                or e["confidence"] >= 0.9
                or e["supporting"]
            )
            and e["type"]
            in ("openworld.silence", "openworld.scene_boundary", "openworld.scene_cut")
        )
    )
    doc = {
        "session_id": sid,
        "layout_key": key,
        "duration_ms": duration,
        "members": members,
        "events": events,
        "speech": speech,
        "boundaries": boundaries,
        "transcript_keys": transcript_keys,
    }
    doc["input_key"] = digest([algorithm.generator(), request.preset, request.options(), doc])
    return doc


class StoryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def generate(
        self,
        sid: str,
        request: StoryRequest,
        *,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        cancel = cancel or threading.Event()

        def check() -> None:
            if cancel.is_set():
                raise StoryCancelled

        report = progress or (lambda *_: None)
        check()
        report(0, 3, "Reading reviewed story evidence")
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            snap = snapshot(conn, sid, request, check)
            settings = digest([request.preset, request.options()])
            cached = conn.execute(
                "SELECT input_key,candidate_count FROM story_generations WHERE session_id=? AND "
                "settings_key=?",
                (sid, settings),
            ).fetchone()
        if cached and cached[0] == snap["input_key"] and not request.force:
            check()
            report(3, 3, "Story candidates already current")
            return {
                "session_id": sid,
                "input_key": snap["input_key"],
                "candidate_count": cached[1],
                "cached": True,
            }
        report(1, 3, "Constructing explainable story windows")
        try:
            docs = algorithm.generate(snap, request.preset, request.options(), check)
        except algorithm.StoryLimitError as exc:
            raise _large() from exc
        if len(docs) > 1000:
            raise _large()
        for doc in docs:
            check()
            load("story-candidate", doc)
        report(2, 3, "Saving story candidates")
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            if snapshot(conn, sid, request, check)["input_key"] != snap["input_key"]:
                raise StoryError(
                    "story.inputs_changed",
                    "Session evidence changed. Generate again before reviewing stories.",
                )
            for doc in docs:
                check()
                existing = conn.execute(
                    "SELECT document_json FROM story_candidates WHERE id=?", (doc["id"],)
                ).fetchone()
                if existing and existing[0] != canonical(doc):
                    raise StoryError(
                        "story.identity_conflict",
                        "Stored candidate identity differs; no stories were replaced.",
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO story_candidates VALUES(?,?,?,?,?,?,?,?)",
                    (
                        doc["id"],
                        sid,
                        settings,
                        snap["input_key"],
                        snap["layout_key"],
                        algorithm.GENERATOR_VERSION,
                        canonical(doc),
                        utc_now(),
                    ),
                )
            conn.execute(
                "INSERT INTO story_generations VALUES(?,?,?,?,?) "
                "ON CONFLICT(session_id,settings_key) "
                "DO UPDATE SET "
                "input_key=excluded.input_key,candidate_count=excluded.candidate_count,"
                "computed_at=excluded.computed_at",
                (sid, settings, snap["input_key"], len(docs), utc_now()),
            )
            check()
        report(3, 3, "Story candidates ready")
        return {
            "session_id": sid,
            "input_key": snap["input_key"],
            "candidate_count": len(docs),
            "cached": False,
        }

    @staticmethod
    def _item(conn: sqlite3.Connection, doc: dict[str, Any], current_key: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT revision,state FROM story_decisions WHERE candidate_id=? ORDER BY revision "
            "DESC LIMIT 1",
            (doc["id"],),
        ).fetchone()
        item = {
            "candidate": normalize(load("story-candidate", doc)),
            "revision": row[0] if row else 0,
            "review_state": row[1] if row else "suggested",
            "current": doc["input_key"] == current_key
            and doc["generator"] == algorithm.generator(),
        }
        if conn.execute("SELECT 1 FROM stories WHERE id=?", (doc["id"],)).fetchone():
            item["project_id"] = doc["id"]
        return item

    def page(
        self,
        sid: str,
        request: StoryRequest,
        *,
        include_history: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        offset = max(0, min(offset, 2**63 - 1))
        limit = max(1, min(100, limit))
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            snap = snapshot(conn, sid, request)
            settings = digest([request.preset, request.options()])
            where = "session_id=? AND settings_key=?"
            args: list[Any] = [sid, settings]
            if not include_history:
                where += (
                    " AND input_key=? AND COALESCE((SELECT state FROM story_decisions d "
                    "WHERE d.candidate_id=story_candidates.id ORDER BY revision DESC LIMIT 1),"
                    "'suggested')<>'rejected'"
                )
                args.append(snap["input_key"])
            total = conn.execute(
                "SELECT count(*) FROM story_candidates WHERE " + where,  # noqa: S608 - fixed SQL clauses
                args,
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT document_json FROM story_candidates WHERE "  # noqa: S608 - fixed SQL clauses
                + where
                + " ORDER BY created_at,id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            result = {
                "schema_version": "1.15",
                "session_id": sid,
                "generator": algorithm.generator(),
                "input_key": snap["input_key"],
                "layout_key": snap["layout_key"],
                "duration_ms": snap["duration_ms"],
                "offset": offset,
                "total": total,
                "items": [self._item(conn, json.loads(r[0]), snap["input_key"]) for r in rows],
            }
        return normalize(load("story-candidates", result))

    def decide(self, sid: str, candidate_id: str, decision: StoryDecision) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            SessionRepository(conn).get(sid)
            row = conn.execute(
                "SELECT document_json FROM story_candidates WHERE id=? AND session_id=?",
                (candidate_id, sid),
            ).fetchone()
            if row is None:
                raise StoryError("story.not_found", "That candidate is not in this session.", 404)
            doc = normalize(load("story-candidate", json.loads(row[0])))
            request = StoryRequest(preset=doc["preset"], **doc["options"])
            key = snapshot(conn, sid, request)["input_key"]
            item = self._item(conn, doc, key)
            if (
                decision.input_key != doc["input_key"]
                or decision.expected_revision != item["revision"]
            ):
                raise StoryError(
                    "story.conflict", "The candidate review changed. Refresh before deciding."
                )
            if decision.state == "accepted" and not item["current"]:
                raise StoryError(
                    "story.stale",
                    "Evidence or generator changed. Generate and review a fresh candidate.",
                )
            now = utc_now()
            exists = conn.execute(
                "SELECT review_state FROM stories WHERE id=?", (candidate_id,)
            ).fetchone()
            if exists and exists[0] == "edited":
                raise StoryError(
                    "story.edited", "This project has editor changes. Manage it in the editor."
                )
            if decision.state == "accepted" and not exists:
                project: dict[str, Any] = {
                    "schema_version": "1.15",
                    "id": candidate_id,
                    "session_id": sid,
                    "title": "Reviewed story",
                    "created_at": now,
                    "updated_at": now,
                    "tracks": [{"kind": "video", "segments": []}],
                    "captions": [],
                    "overlays": [],
                    "audio": {"gain_db": 0, "mute_ranges": []},
                }
                position = 0
                for i, r in enumerate(doc["source_ranges"]):
                    project["tracks"][0]["segments"].append(
                        {
                            "id": algorithm.stable_id("seg", [candidate_id, i, r]),
                            "asset_id": r["asset_id"],
                            "source_in_ms": r["source_in_ms"],
                            "source_out_ms": r["source_out_ms"],
                            "timeline_start_ms": position,
                            "crop": {"mode": "fit", "keyframes": []},
                        }
                    )
                    position += r["source_out_ms"] - r["source_in_ms"]
                StoryRepository(conn).save(
                    Story(
                        id=candidate_id,
                        session_id=sid,
                        title="Reviewed story",
                        preset=doc["preset"],
                        score=doc["score"],
                        score_components=doc["score_components"],
                        timeline=Project.model_validate(normalize(load("project", project))),
                        review_state="accepted",
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif exists:
                conn.execute(
                    "UPDATE stories SET review_state=?,updated_at=? WHERE id=?",
                    (decision.state, now, candidate_id),
                )
            conn.execute(
                "INSERT INTO story_decisions VALUES(?,?,?,?,?)",
                (candidate_id, item["revision"] + 1, decision.state, decision.input_key, now),
            )
            return self._item(conn, doc, key)
