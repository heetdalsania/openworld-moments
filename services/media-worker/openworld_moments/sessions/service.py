# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build, recompute, and correct sessions (M11).

* ``recompute`` (the ``group`` job) re-estimates capture times, then rebuilds the
  *unreviewed* sessions from all assets that are not locked. Locked assets are the
  members of corrected or confirmed sessions, and of sessions that stories use; they
  are never moved. Existing session IDs are kept wherever membership allows, and a
  second run over unchanged data changes nothing.
* Corrections (merge, split, reorder, remove, confirm) run in one transaction each,
  mark the touched sessions ``corrected`` (or ``confirmed``), and are logged in
  ``session_corrections``. Because automatic runs skip those sessions, corrections
  survive every recomputation.

Everything here reads and writes database rows only: no media file is opened,
moved, or changed.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from pathlib import PurePath
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments.ids import new_id
from openworld_moments.sessions import capture, grouping
from openworld_moments.storage import (
    Database,
    NotFoundError,
    Session,
    SessionAsset,
    SessionRepository,
    SettingsRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

MAX_GAP_SETTING = "sessions.max_gap_ms"
Progress = Callable[[int, int, str], None]


class SessionError(Exception):
    """A correction the service refuses. ``code`` maps to an API error."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class GroupCancelled(Exception):
    pass


@dataclass(frozen=True)
class _Row:
    """One asset as grouping sees it, plus what estimation needs."""

    facts: grouping.AssetFacts
    signals: capture.Signals
    basis: tuple[str, ...]
    notes: tuple[str, ...]


def _facts_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.id, a.original_name, a.source_kind, a.captured_at, a.captured_at_confidence,
               a.captured_at_basis_json, a.container_created_at, a.duration_ms, a.created_at,
               a.video_codec, a.width, a.height, a.rotation, a.fps_num, a.fps_den,
               a.avg_fps_num, a.avg_fps_den,
               i.source_path, i.mtime_ns, i.job_id
        FROM media_assets a
        LEFT JOIN asset_imports i ON i.id = (
            SELECT id FROM asset_imports WHERE asset_id = a.id ORDER BY first_seen_at, id LIMIT 1
        )
        ORDER BY a.created_at, a.id
        """
    ).fetchall()


def _upright(row: sqlite3.Row) -> tuple[int | None, int | None]:
    if row["rotation"] in (90, 270):
        return row["height"], row["width"]
    return row["width"], row["height"]


def _fps(row: sqlite3.Row) -> Fraction | None:
    num, den = row["avg_fps_num"] or row["fps_num"], row["avg_fps_den"] or row["fps_den"]
    return Fraction(num, den) if num and den else None


def _folder(path: str | None) -> str | None:
    return str(PurePath(path).parent) if path else None


class SessionService:
    def __init__(self, database: Database, *, zone: Any = None) -> None:
        self.database = database
        self.zone = zone
        self._lock = threading.Lock()

    # -- facts ------------------------------------------------------------------------

    def _rows(self, conn: sqlite3.Connection) -> list[_Row]:
        raw = _facts_rows(conn)
        # mtimes from one import job that sit seconds apart are copy times.
        by_job: dict[str | None, list[int]] = {}
        for index, row in enumerate(raw):
            by_job.setdefault(row["job_id"], []).append(index)
        artefacts: set[int] = set()
        for indexes in by_job.values():
            flagged = capture.copy_artefacts([raw[i]["mtime_ns"] for i in indexes])
            artefacts.update(indexes[k] for k in flagged)
        rows: list[_Row] = []
        for index, row in enumerate(raw):
            signals = capture.Signals(
                original_name=row["original_name"],
                container_created_at=row["container_created_at"],
                mtime_ns=row["mtime_ns"],
                duration_ms=row["duration_ms"],
            )
            stored_basis = tuple(capture_basis(row["captured_at_basis_json"]))
            if "user" in stored_basis:
                estimate = capture.Estimate(
                    row["captured_at"], float(row["captured_at_confidence"]), stored_basis
                )
            else:
                estimate = capture.estimate(signals, self.zone)
                if index in artefacts:
                    estimate = capture.with_copy_artefact(estimate)
            width, height = _upright(row)
            facts = grouping.AssetFacts(
                id=row["id"],
                source_key=grouping.source_key(row["source_kind"], _folder(row["source_path"])),
                captured_at=estimate.captured_at,
                capture_confidence=estimate.confidence,
                duration_ms=row["duration_ms"],
                created_at=row["created_at"],
                import_job=row["job_id"],
                video_codec=row["video_codec"],
                width=width,
                height=height,
                fps=_fps(row),
            )
            rows.append(_Row(facts, signals, estimate.basis, estimate.notes))
        return rows

    def settings(self, conn: sqlite3.Connection, params: Mapping[str, Any]) -> grouping.Settings:
        value = params.get("max_gap_ms")
        if value is None:
            with contextlib.suppress(NotFoundError, KeyError):
                value = SettingsRepository(conn).get(MAX_GAP_SETTING)
        if isinstance(value, int) and not isinstance(value, bool):
            return grouping.Settings(max_gap_ms=value)
        return grouping.Settings()

    # -- recompute --------------------------------------------------------------------

    def recompute(
        self,
        params: Mapping[str, Any],
        *,
        cancel: threading.Event | None = None,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """The ``group`` job (contract GroupRequest → GroupResult)."""
        report = progress or (lambda *_: None)
        with self._lock, contextlib.closing(self.database.connect()) as conn:
            report(0, 3, "Reading assets")
            with transaction(conn):  # one snapshot and one write: corrections wait
                rows = self._rows(conn)
                if cancel is not None and cancel.is_set():
                    raise GroupCancelled
                settings = self.settings(conn, params)
                updated_times = self._store_capture_times(conn, rows)
                report(1, 3, "Grouping")
                sessions = SessionRepository(conn)
                locked_ids = self._locked_sessions(conn, sessions)
                locked_assets = {
                    link.asset_id for sid in locked_ids for link in sessions.assets(sid)
                }
                free = [r for r in rows if r.facts.id not in locked_assets]
                groups = grouping.group([r.facts for r in free], settings) if free else []
                if cancel is not None and cancel.is_set():
                    raise GroupCancelled
                report(2, 3, "Saving sessions")
                counts = self._apply(conn, sessions, groups, rows, settings, locked_ids)
        result = {
            "considered_assets": len(rows),
            "locked_assets": len(locked_assets),
            "capture_times_updated": updated_times,
            **counts,
        }
        report(3, 3, _summary(result))
        return result

    @staticmethod
    def _store_capture_times(conn: sqlite3.Connection, rows: Sequence[_Row]) -> int:
        changed = 0
        for row in rows:
            facts = row.facts
            current = conn.execute(
                "SELECT captured_at, captured_at_confidence, captured_at_basis_json "
                "FROM media_assets WHERE id = ?",
                (facts.id,),
            ).fetchone()
            basis_json = _basis_json(row.basis)
            new = (facts.captured_at, facts.capture_confidence, basis_json)
            if tuple(current) != new:
                conn.execute(
                    "UPDATE media_assets SET captured_at = ?, captured_at_confidence = ?, "
                    "captured_at_basis_json = ? WHERE id = ?",
                    (*new, facts.id),
                )
                changed += 1
        return changed

    @staticmethod
    def _locked_sessions(conn: sqlite3.Connection, sessions: SessionRepository) -> list[str]:
        rows = conn.execute(
            "SELECT id FROM sessions WHERE review_state <> 'unreviewed' "
            "OR id IN (SELECT session_id FROM stories WHERE session_id IS NOT NULL) ORDER BY id"
        ).fetchall()
        return [r["id"] for r in rows]

    def _apply(
        self,
        conn: sqlite3.Connection,
        sessions: SessionRepository,
        groups: list[grouping.Group],
        rows: list[_Row],
        settings: grouping.Settings,
        locked: list[str],
    ) -> dict[str, int]:
        notes = {r.facts.id: r.notes for r in rows}
        existing = {
            s.id: [link.asset_id for link in sessions.assets(s.id)]
            for s in sessions.all()
            if s.id not in locked
        }
        used: set[str] = set()
        counts = dict.fromkeys(
            ("sessions_created", "sessions_updated", "sessions_unchanged", "sessions_removed"), 0
        )
        plans: list[tuple[str | None, grouping.Group]] = []
        for group_ in groups:
            members = [a.id for a in group_.assets]
            best: str | None = None
            best_score = (0, 0)
            for candidate in sorted(existing):
                if candidate in used:
                    continue
                shared = len(set(members) & set(existing[candidate]))
                score = (int(existing[candidate] == members), shared)
                if shared and score > best_score:
                    best, best_score = candidate, score
            if best is not None:
                used.add(best)
            plans.append((best, group_))
        # Remove sessions that no group continues before reusing their members.
        for stale in sorted(set(existing) - used):
            sessions.delete(stale)
            counts["sessions_removed"] += 1
        for sid, group_ in plans:
            group_notes = [n for a in group_.assets for n in notes.get(a.id, ())]
            evidence = grouping.evidence(group_, settings, group_notes)
            links = self._links(sid or "", group_.assets, chronological=True)
            started, ended = _span(group_.assets)
            if sid is None:
                session = Session(
                    id=new_id("ses"),
                    title=_title(started),
                    started_at=started,
                    ended_at=ended,
                    grouping_confidence=group_.confidence,
                    review_state="unreviewed",
                    created_at=utc_now(),
                    grouping=evidence,
                    updated_at=utc_now(),
                )
                sessions.add(session)
                sessions.replace_assets(session.id, self._links(session.id, group_.assets))
                counts["sessions_created"] += 1
                continue
            current = sessions.get(sid)
            current_links = sessions.assets(sid)
            wanted = Session(
                **{
                    **current.model_dump(),
                    "title": _title(started),
                    "started_at": started,
                    "ended_at": ended,
                    "grouping_confidence": group_.confidence,
                    "grouping": evidence,
                }
            )
            if wanted == current and current_links == links:
                counts["sessions_unchanged"] += 1
                continue
            sessions.update(wanted.model_copy(update={"updated_at": utc_now()}))
            sessions.replace_assets(sid, links)
            counts["sessions_updated"] += 1
        return counts

    @staticmethod
    def _links(
        session_id: str, assets: Sequence[grouping.AssetFacts], *, chronological: bool = True
    ) -> list[SessionAsset]:
        starts = grouping.offsets(list(assets), chronological=chronological)
        return [
            SessionAsset(
                session_id=session_id,
                asset_id=a.id,
                order_index=i,
                session_start_ms=starts[i],
            )
            for i, a in enumerate(assets)
        ]

    # -- corrections ------------------------------------------------------------------

    def _facts_by_id(self, conn: sqlite3.Connection) -> dict[str, grouping.AssetFacts]:
        return {r.facts.id: r.facts for r in self._rows(conn)}

    def _members(
        self, sessions: SessionRepository, facts: Mapping[str, grouping.AssetFacts], sid: str
    ) -> list[grouping.AssetFacts]:
        return [facts[link.asset_id] for link in sessions.assets(sid)]

    def _save(
        self,
        sessions: SessionRepository,
        session: Session,
        members: Sequence[grouping.AssetFacts],
        *,
        chronological: bool,
        new: bool = False,
    ) -> None:
        started, ended = _span(members)
        update: dict[str, Any] = {"started_at": started, "ended_at": ended, "updated_at": utc_now()}
        if session.review_state == "corrected":
            # The user decided the membership: automatic evidence no longer applies.
            update.update({"grouping": None, "grouping_confidence": None})
        session = session.model_copy(update=update)
        if new:
            sessions.add(session)
        else:
            sessions.update(session)
        sessions.replace_assets(
            session.id, self._links(session.id, members, chronological=chronological)
        )

    def _correct(
        self, action: Callable[[sqlite3.Connection, SessionRepository], list[str]]
    ) -> list[dict[str, Any]]:
        with self._lock, contextlib.closing(self.database.connect()) as conn:
            with transaction(conn):
                ids = action(conn, SessionRepository(conn))
            return [self.doc(conn, sid) for sid in ids]

    def _get(self, sessions: SessionRepository, sid: str) -> Session:
        try:
            return sessions.get(sid)
        except NotFoundError as exc:
            raise SessionError("session.not_found", f"session {sid} not found", status=404) from exc

    def merge(self, session_ids: Sequence[str]) -> dict[str, Any]:
        """Combine sessions into the first one, in capture-time order."""

        def run(conn: sqlite3.Connection, sessions: SessionRepository) -> list[str]:
            if len(session_ids) < 2 or len(set(session_ids)) != len(session_ids):
                raise SessionError(
                    "session.invalid_request", "Choose two or more sessions.", status=422
                )
            targets = [self._get(sessions, sid) for sid in session_ids]
            facts = self._facts_by_id(conn)
            members: list[grouping.AssetFacts] = []
            for target in targets:
                members.extend(self._members(sessions, facts, target.id))
            members.sort(key=grouping.ordering_key)
            keep = targets[0]
            for other in targets[1:]:
                if sessions.has_stories(other.id):
                    raise SessionError(
                        "session.in_use", "A merged session has stories; merge into it instead."
                    )
                sessions.replace_assets(other.id, [])
                sessions.delete(other.id)
            keep = keep.model_copy(update={"review_state": "corrected"})
            self._save(sessions, keep, members, chronological=True)
            sessions.log_correction(
                "merge", list(session_ids), [m.id for m in members], {"kept": keep.id}
            )
            return [keep.id]

        return self._correct(run)[0]

    def split(self, session_id: str, after_asset_id: str) -> list[dict[str, Any]]:
        """Clips up to and including ``after_asset_id`` stay; the rest form a new session."""

        def run(conn: sqlite3.Connection, sessions: SessionRepository) -> list[str]:
            session = self._get(sessions, session_id)
            facts = self._facts_by_id(conn)
            members = self._members(sessions, facts, session_id)
            ids = [m.id for m in members]
            if after_asset_id not in ids:
                raise SessionError(
                    "session.invalid_request", "That clip is not in this session.", status=422
                )
            cut = ids.index(after_asset_id) + 1
            if cut == len(ids):
                raise SessionError(
                    "session.invalid_request", "Nothing comes after that clip.", status=422
                )
            chronological = _is_chronological(members)
            session = session.model_copy(update={"review_state": "corrected"})
            self._save(sessions, session, members[:cut], chronological=chronological)
            rest = members[cut:]
            started, _ = _span(rest)
            new = Session(
                id=new_id("ses"),
                title=_title(started),
                review_state="corrected",
                grouping_confidence=None,
                created_at=utc_now(),
            )
            self._save(sessions, new, rest, chronological=chronological, new=True)
            sessions.log_correction(
                "split", [session_id, new.id], ids, {"after_asset_id": after_asset_id}
            )
            return [session_id, new.id]

        return self._correct(run)

    def reorder(self, session_id: str, asset_ids: Sequence[str]) -> dict[str, Any]:
        """Put the members in the user's order. Clips are then placed end to end."""

        def run(conn: sqlite3.Connection, sessions: SessionRepository) -> list[str]:
            session = self._get(sessions, session_id)
            facts = self._facts_by_id(conn)
            members = self._members(sessions, facts, session_id)
            if sorted(asset_ids) != sorted(m.id for m in members) or len(set(asset_ids)) != len(
                asset_ids
            ):
                raise SessionError(
                    "session.invalid_request",
                    "List every clip of the session exactly once.",
                    status=422,
                )
            ordered = [facts[a] for a in asset_ids]
            session = session.model_copy(update={"review_state": "corrected"})
            self._save(sessions, session, ordered, chronological=_is_chronological(ordered))
            sessions.log_correction("reorder", [session_id], list(asset_ids))
            return [session_id]

        return self._correct(run)[0]

    def remove(self, session_id: str, asset_id: str) -> list[dict[str, Any]]:
        """Mark a clip as unrelated: it gets a corrected session of its own."""

        def run(conn: sqlite3.Connection, sessions: SessionRepository) -> list[str]:
            session = self._get(sessions, session_id)
            facts = self._facts_by_id(conn)
            members = self._members(sessions, facts, session_id)
            if asset_id not in [m.id for m in members]:
                raise SessionError(
                    "session.invalid_request", "That clip is not in this session.", status=422
                )
            if len(members) == 1:
                session = session.model_copy(update={"review_state": "corrected"})
                self._save(sessions, session, members, chronological=True)
                sessions.log_correction("remove", [session_id], [asset_id])
                return [session_id]
            rest = [m for m in members if m.id != asset_id]
            session = session.model_copy(update={"review_state": "corrected"})
            self._save(sessions, session, rest, chronological=_is_chronological(rest))
            alone = Session(
                id=new_id("ses"),
                title=_title(facts[asset_id].captured_at),
                review_state="corrected",
                grouping_confidence=None,
                created_at=utc_now(),
            )
            self._save(sessions, alone, [facts[asset_id]], chronological=True, new=True)
            sessions.log_correction("remove", [session_id, alone.id], [asset_id])
            return [session_id, alone.id]

        return self._correct(run)

    def confirm(self, session_id: str) -> dict[str, Any]:
        def run(conn: sqlite3.Connection, sessions: SessionRepository) -> list[str]:
            session = self._get(sessions, session_id)
            if session.review_state == "unreviewed":
                sessions.update(
                    session.model_copy(
                        update={"review_state": "confirmed", "updated_at": utc_now()}
                    )
                )
            members = [link.asset_id for link in sessions.assets(session_id)]
            sessions.log_correction("confirm", [session_id], members)
            return [session_id]

        return self._correct(run)[0]

    # -- documents --------------------------------------------------------------------

    def doc(self, conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
        """The contract ``Session`` (raises SessionError when unknown)."""
        sessions = SessionRepository(conn)
        session = self._get(sessions, session_id)
        members = []
        for link in sessions.assets(session_id):
            row = conn.execute(
                "SELECT duration_ms, captured_at, captured_at_confidence, captured_at_basis_json "
                "FROM media_assets WHERE id = ?",
                (link.asset_id,),
            ).fetchone()
            member: dict[str, Any] = {
                "asset_id": link.asset_id,
                "order_index": link.order_index,
                "session_start_ms": link.session_start_ms,
                "duration_ms": row["duration_ms"],
            }
            if row["captured_at"]:
                member["capture_time"] = {
                    "captured_at": row["captured_at"],
                    "confidence": row["captured_at_confidence"],
                    "basis": capture_basis(row["captured_at_basis_json"]),
                }
            members.append(member)
        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": session.id,
            "title": session.title,
            "review_state": session.review_state,
            "grouping_confidence": session.grouping_confidence,
            "assets": members,
            "grouping": session.grouping,
            "created_at": session.created_at,
        }
        for key in ("started_at", "ended_at", "updated_at"):
            value = getattr(session, key)
            if value:
                doc[key] = value
        return normalize(load("session", doc))

    def list_docs(
        self, conn: sqlite3.Connection, *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        sessions = SessionRepository(conn)
        return [self.doc(conn, s.id) for s in sessions.newest(limit=limit, offset=offset)]

    def corrections(self, conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
        self._get(SessionRepository(conn), session_id)
        return SessionRepository(conn).corrections(session_id)


# -- helpers --------------------------------------------------------------------------

_BASIS_ORDER = ("container_metadata", "filename", "filesystem_mtime", "import_order", "user")


def capture_basis(text: str | None) -> list[str]:
    try:
        value = json.loads(text) if text else []
    except ValueError:
        value = []
    return [b for b in value if b in _BASIS_ORDER] if isinstance(value, list) else []


def _basis_json(basis: Sequence[str]) -> str:
    return json.dumps(list(basis), separators=(",", ":"))


def _span(assets: Sequence[grouping.AssetFacts]) -> tuple[str | None, str | None]:
    if not assets:
        return None, None
    start = min(a.start for a in assets)
    end = max(a.start + timedelta(milliseconds=a.duration_ms) for a in assets)
    return capture.iso(start), capture.iso(end)


def _title(started: str | None) -> str:
    when = capture.parse_utc(started)
    if when is None:
        return "Session"
    return f"Session starting {when:%Y-%m-%d %H:%M} UTC"


def _is_chronological(assets: Sequence[grouping.AssetFacts]) -> bool:
    keys = [grouping.ordering_key(a) for a in assets]
    return keys == sorted(keys)


def _summary(result: Mapping[str, int]) -> str:
    parts = [
        (result["sessions_created"], "created"),
        (result["sessions_updated"], "updated"),
        (result["sessions_unchanged"], "unchanged"),
        (result["sessions_removed"], "removed"),
    ]
    return ", ".join(f"{n} {label}" for n, label in parts if n) or "No sessions"
