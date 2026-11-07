# SPDX-License-Identifier: AGPL-3.0-or-later
"""Align adjacent session clips and apply the results to session timelines (M12).

* The ``align`` job walks every adjacent pair (A, B) of the chosen sessions. A pair
  with a current result (same algorithm version) is a cache hit; otherwise both
  clips get current fingerprints (M06, computed on demand) and ``overlap.align``
  runs. Each result is committed on its own, so an interrupted job resumes.
* Sessions are then laid out again with the shared layout (``grouping.layout``):
  only ``matched`` results and user overrides move a clip; everything else leaves
  both clips whole.
* A user override per pair (an overlap in ms, 0 for "no overlap") always wins and
  survives recomputation.

Only database rows change: no media file is opened for writing, moved, or deleted.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments.alignment.overlap import (
    ALIGN_ALGORITHM,
    ALIGN_VERSION,
    Alignment,
    Side,
    align,
)
from openworld_moments.fingerprints.service import (
    FingerprintCancelled,
    Fingerprinter,
    is_current,
)
from openworld_moments.sessions.service import SessionError, SessionService
from openworld_moments.storage import (
    AssetRepository,
    Database,
    FingerprintRepository,
    NotFoundError,
    OverlapRepository,
    OverlapRow,
    SessionRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

Progress = Callable[[int, int, str], None]
STATUSES = ("matched", "weak", "ambiguous", "no_match", "insufficient")


class AlignCancelled(Exception):
    pass


class Aligner:
    def __init__(self, database: Database, fingerprinter: Fingerprinter | None = None) -> None:
        self.database = database
        self.fingerprinter = fingerprinter
        self.sessions = SessionService(database)

    # -- pairs ------------------------------------------------------------------------

    @staticmethod
    def _targets(conn: sqlite3.Connection, requested: Sequence[str] | None) -> list[str]:
        repo = SessionRepository(conn)
        if requested:
            for sid in requested:
                try:
                    repo.get(sid)
                except NotFoundError as exc:
                    raise SessionError(
                        "session.not_found", f"session {sid} not found", status=404
                    ) from exc
            return list(requested)
        return [s.id for s in repo.all()]

    @staticmethod
    def _pairs(conn: sqlite3.Connection, session_ids: Sequence[str]) -> list[tuple[str, str]]:
        repo = SessionRepository(conn)
        seen: dict[tuple[str, str], None] = {}
        for sid in session_ids:
            members = [link.asset_id for link in repo.assets(sid)]
            for pair in pairwise(members):
                seen.setdefault(pair, None)
        return list(seen)

    # -- the job ----------------------------------------------------------------------

    def run(
        self,
        params: Mapping[str, Any],
        *,
        cancel: threading.Event | None = None,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        """The ``align`` job (contract AlignRequest → AlignResult)."""
        report = progress or (lambda *_: None)
        cancel = cancel or threading.Event()
        force = bool(params.get("force", False))
        counts: dict[str, int] = dict.fromkeys(
            ("pairs_considered", "computed", "cached", "fingerprints_computed", "sessions_updated"),
            0,
        )
        counts.update(dict.fromkeys(STATUSES, 0))
        with contextlib.closing(self.database.connect()) as conn:
            targets = self._targets(conn, params.get("session_ids"))
            pairs = self._pairs(conn, targets)
            counts["pairs_considered"] = len(pairs)
            total = max(1, len(pairs))
            report(0, total, f"{len(pairs)} clip pairs")
            repo = OverlapRepository(conn)
            for index, (a, b) in enumerate(pairs, start=1):
                if cancel.is_set():
                    raise AlignCancelled
                existing = repo.get(a, b)
                current = (
                    existing is not None
                    and existing.status != "pending"
                    and (existing.algorithm, existing.version) == (ALIGN_ALGORITHM, ALIGN_VERSION)
                )
                if current and not force and existing is not None:
                    counts["cached"] += 1
                    counts[existing.status] += 1
                else:
                    result, fingerprinted = self._align_pair(conn, a, b, cancel)
                    counts["fingerprints_computed"] += fingerprinted
                    with transaction(conn):
                        repo.save_result(
                            OverlapRow(
                                asset_a=a,
                                asset_b=b,
                                algorithm=ALIGN_ALGORITHM,
                                version=ALIGN_VERSION,
                                status=result.status,
                                offset_ms=result.offset_ms,
                                overlap_ms=result.overlap_ms,
                                confidence=result.confidence,
                                evidence=result.evidence,
                                computed_at=utc_now(),
                            )
                        )
                    counts["computed"] += 1
                    counts[result.status] += 1
                report(index, total, f"{index} of {len(pairs)} pairs")
            with transaction(conn):
                for sid in targets:
                    counts["sessions_updated"] += self.sessions.relayout(conn, sid)
        report(1 if not pairs else len(pairs), total, _summary(counts))
        return counts

    def _align_pair(
        self, conn: sqlite3.Connection, a: str, b: str, cancel: threading.Event
    ) -> tuple[Alignment, int]:
        fingerprinted = 0
        prints: dict[str, dict[str, Any]] = {}
        for asset_id in (a, b):
            stored = FingerprintRepository(conn).for_asset(asset_id)
            if not is_current(stored.get("frames"), "frames") and self.fingerprinter is not None:
                try:
                    outcome = self.fingerprinter.fingerprint_asset(conn, asset_id, cancel=cancel)
                except FingerprintCancelled as exc:
                    raise AlignCancelled from exc
                fingerprinted += outcome.status == "updated"
                stored = FingerprintRepository(conn).for_asset(asset_id)
            frames = stored.get("frames")
            if frames is None or not is_current(frames, "frames"):
                return (
                    Alignment(
                        "insufficient",
                        evidence={"reason": "fingerprints_unavailable", "asset_id": asset_id},
                    ),
                    fingerprinted,
                )
            audio = stored.get("audio")
            prints[asset_id] = {
                "frames": frames.data,
                "audio": audio.data if audio is not None and is_current(audio, "audio") else None,
                "duration_ms": AssetRepository(conn).get(asset_id).duration_ms,
            }
        first, second = prints[a], prints[b]
        result = align(
            Side.tail(first["duration_ms"], first["frames"], first["audio"]),
            Side.head(second["duration_ms"], second["frames"], second["audio"]),
        )
        return result, fingerprinted

    # -- overrides and documents ------------------------------------------------------

    def set_override(
        self, session_id: str, asset_id: str, overlap_ms: int | None
    ) -> dict[str, Any]:
        """Set (or clear) the overlap between ``asset_id`` and the clip before it."""
        with contextlib.closing(self.database.connect()) as conn:
            with transaction(conn):
                repo = SessionRepository(conn)
                try:
                    repo.get(session_id)
                except NotFoundError as exc:
                    raise SessionError(
                        "session.not_found", f"session {session_id} not found", status=404
                    ) from exc
                members = [link.asset_id for link in repo.assets(session_id)]
                if asset_id not in members or members.index(asset_id) == 0:
                    raise SessionError(
                        "session.invalid_request",
                        "Choose a clip that follows another clip in this session.",
                        status=422,
                    )
                previous = members[members.index(asset_id) - 1]
                if overlap_ms is not None:
                    assets = AssetRepository(conn)
                    limit = min(assets.get(previous).duration_ms, assets.get(asset_id).duration_ms)
                    if not 0 <= overlap_ms <= limit:
                        raise SessionError(
                            "session.invalid_request",
                            f"The overlap must be between 0 and {limit} ms.",
                            status=422,
                        )
                OverlapRepository(conn).set_override(
                    previous,
                    asset_id,
                    overlap_ms,
                    algorithm=ALIGN_ALGORITHM,
                    version=ALIGN_VERSION,
                )
                repo.log_correction(
                    "overlap",
                    [session_id],
                    [previous, asset_id],
                    {"overlap_ms": overlap_ms},
                )
                self.sessions.relayout(conn, session_id)
            return self.sessions.doc(conn, session_id)

    def overlaps_doc(self, conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
        """Contract ``AssetOverlap`` for every adjacent pair of the session, in order."""
        repo = SessionRepository(conn)
        try:
            repo.get(session_id)
        except NotFoundError as exc:
            raise SessionError(
                "session.not_found", f"session {session_id} not found", status=404
            ) from exc
        members = [link.asset_id for link in repo.assets(session_id)]
        overlaps = OverlapRepository(conn)
        effective = overlaps.effective(
            list(pairwise(members)),
            algorithm=ALIGN_ALGORITHM,
            version=ALIGN_VERSION,
        )
        docs = []
        for a, b in pairwise(members):
            row = overlaps.get(a, b)
            doc: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "asset_a": a,
                "asset_b": b,
                "algorithm": row.algorithm if row else ALIGN_ALGORITHM,
                "version": row.version if row else ALIGN_VERSION,
                "status": row.status if row else "pending",
                "current": row is not None
                and (row.algorithm, row.version) == (ALIGN_ALGORITHM, ALIGN_VERSION),
                "evidence": row.evidence if row else {},
            }
            if row is not None:
                doc["computed_at"] = row.computed_at
                for key in ("offset_ms", "overlap_ms", "confidence"):
                    value = getattr(row, key)
                    if value is not None:
                        doc[key] = value
                if row.override_overlap_ms is not None:
                    doc["override"] = {
                        "overlap_ms": row.override_overlap_ms,
                        "set_at": row.overridden_at,
                    }
            applied = effective.get((a, b))
            doc["applied"] = (
                {
                    "overlap_ms": applied.overlap_ms,
                    "source": applied.source,
                    **(
                        {"confidence": applied.confidence} if applied.confidence is not None else {}
                    ),
                }
                if applied is not None
                else {"overlap_ms": 0, "source": "none"}
            )
            docs.append(normalize(load("overlap", doc)))
        return docs


def _summary(counts: Mapping[str, int]) -> str:
    parts = [
        (counts["matched"], "overlapping"),
        (counts["weak"] + counts["ambiguous"], "uncertain"),
        (counts["no_match"], "no overlap"),
        (counts["insufficient"], "not enough data"),
    ]
    return ", ".join(f"{n} {label}" for n, label in parts if n) or "No clip pairs"
