# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compute, store, and compare fingerprints; run the restartable backfill (M06).

Each asset is committed on its own, so an interrupted backfill resumes with the
assets that still lack a current fingerprint. Nothing here writes to a source
file or deletes an asset: duplicate candidates are only recorded for review.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.fingerprint_schema import (
    AssetFingerprints,
    DuplicateCandidate,
    FingerprintResult,
)

from openworld_moments.fingerprints import algorithms as alg
from openworld_moments.ingest.library import LibraryPaths
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import (
    AssetLocation,
    AssetRepository,
    Database,
    DuplicateCandidateRepository,
    DuplicateCandidateRow,
    FingerprintRepository,
    NotFoundError,
    StoredFingerprint,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

#: Current algorithm per fingerprint kind. Stored rows that differ are stale.
CURRENT: dict[str, tuple[str, int]] = {
    "fast": (alg.FAST_ALGORITHM, alg.FAST_VERSION),
    "frames": (alg.FRAMES_ALGORITHM, alg.FRAMES_VERSION),
    "audio": (alg.AUDIO_ALGORITHM, alg.AUDIO_VERSION),
}
MAX_CANDIDATES_PER_ASSET = 20

Progress = Callable[[int, int, str], None]


class FingerprintFailure(Exception):
    """A fingerprint job fails as a whole (e.g. FFmpeg is not usable)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class FingerprintCancelled(Exception):
    pass


@dataclass
class AssetOutcome:
    status: str  # 'updated' | 'up_to_date' | 'unavailable' | 'failed'
    new_candidates: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None


def is_current(stored: StoredFingerprint | None, kind: str) -> bool:
    return stored is not None and (stored.algorithm, stored.version) == CURRENT[kind]


def candidate_doc(row: DuplicateCandidateRow) -> dict[str, Any]:
    """A stored row as a contract ``DuplicateCandidate``."""
    model = DuplicateCandidate.model_validate(
        {
            "id": row.id,
            "asset_ids": [row.asset_a, row.asset_b],
            "kind": row.kind,
            "score": row.score,
            "evidence": row.evidence,
            "algorithm": row.algorithm,
            "version": row.version,
            "review_state": row.review_state,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
    return normalize(model)


def fingerprints_doc(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    """The contract ``AssetFingerprints`` for one asset (raises NotFoundError)."""
    asset = AssetRepository(conn).get(asset_id)
    stored = FingerprintRepository(conn).for_asset(asset_id)
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asset_id": asset_id,
        "sha256": asset.sha256,
    }
    for kind, key in (("fast", "fast_hash"), ("frames", "frames"), ("audio", "audio")):
        fp = stored.get(kind)
        if fp is None:
            continue
        doc[key] = {
            "algorithm": fp.algorithm,
            "version": fp.version,
            **fp.data,
            "computed_at": fp.computed_at,
        }
    model: AssetFingerprints = load("fingerprint", doc)  # type: ignore[assignment]
    return normalize(model)


class Fingerprinter:
    """Runs on a job thread; opens its own database connections."""

    def __init__(
        self,
        database: Database,
        tools: MediaTools,
        *,
        library: LibraryPaths | None = None,
        decode_timeout_s: float = alg.DECODE_TIMEOUT_S,
    ) -> None:
        self.database = database
        self.tools = tools
        self.library = library or LibraryPaths.for_database(database.path)
        self.decode_timeout_s = decode_timeout_s

    # -- sources ----------------------------------------------------------------------

    def source_path(self, location: AssetLocation) -> Path | None:
        """Where the asset's bytes can be read now, or None."""
        if location.import_mode == "managed" and location.managed_path:
            path = self.library.resolve_managed(location.managed_path)
        elif location.original_path:
            path = Path(location.original_path)
        else:
            path = None
        if path is None:
            return None
        try:
            info = path.stat()
        except OSError:
            return None
        if location.size_bytes is not None and info.st_size != location.size_bytes:
            return None  # replaced: not this asset's bytes any more
        return path

    def ffmpeg(self) -> ToolInfo:
        tool = self.tools.tool("ffmpeg")
        if not tool.ok:
            raise FingerprintFailure(
                "tool.ffmpeg_missing" if tool.status == "missing" else f"tool.ffmpeg_{tool.status}",
                f"FFmpeg is not usable: {tool.problem}. Install FFmpeg 6.0 or newer, "
                "or set OWM_FFMPEG.",
                retryable=True,
            )
        return tool

    # -- one asset --------------------------------------------------------------------

    def fingerprint_asset(
        self,
        conn: sqlite3.Connection,
        asset_id: str,
        *,
        cancel: threading.Event,
        force: bool = False,
    ) -> AssetOutcome:
        assets = AssetRepository(conn)
        asset = assets.get(asset_id)
        location = assets.location(asset_id)
        stored = FingerprintRepository(conn).for_asset(asset_id)
        wanted = ["fast"]
        if asset.video is not None:
            wanted.append("frames")
        if asset.audio:
            wanted.append("audio")
        todo = [k for k in wanted if force or not is_current(stored.get(k), k)]
        if not todo:
            return AssetOutcome("up_to_date", candidates=self._candidate_ids(conn, asset_id))
        path = self.source_path(location)
        if path is None:
            return AssetOutcome("unavailable")
        try:
            new = self._compute(path, todo, asset.duration_ms, location.size_bytes, cancel)
        except alg.DecodeCancelled as exc:
            raise FingerprintCancelled from exc
        except alg.DecodeError as exc:
            error = {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
            return AssetOutcome("failed", error=error)
        except OSError as exc:
            error = {
                "code": "media.unreadable",
                "message": f"The file cannot be read: {exc.strerror}.",
                "retryable": True,
            }
            return AssetOutcome("failed", error=error)
        now = utc_now()
        with transaction(conn):
            repo = FingerprintRepository(conn)
            for kind, data in new.items():
                algorithm, version = CURRENT[kind]
                repo.put(
                    StoredFingerprint(
                        asset_id=asset_id,
                        kind=kind,  # type: ignore[arg-type]
                        algorithm=algorithm,
                        version=version,
                        data=data,
                        computed_at=now,
                    )
                )
                if kind == "fast":
                    assets.set_fast_hash(asset_id, data["value"])
        new_candidates: list[str] = []
        if "frames" in new:
            new_candidates = self.find_candidates(conn, asset_id)
        return AssetOutcome(
            "updated",
            new_candidates=new_candidates,
            candidates=self._candidate_ids(conn, asset_id),
        )

    def _compute(
        self,
        path: Path,
        kinds: list[str],
        duration_ms: int,
        size: int | None,
        cancel: threading.Event,
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if "fast" in kinds:
            out["fast"] = {
                "value": alg.fast_hash(path, size if size is not None else path.stat().st_size)
            }
        head, tail = alg.windows(duration_ms)
        if "frames" in kinds or "audio" in kinds:
            ffmpeg = self.ffmpeg()
            if "frames" in kinds:
                out["frames"] = {
                    "sample_fps": alg.SAMPLE_FPS,
                    "window_ms": alg.WINDOW_MS,
                    "head": alg.frame_hashes(
                        ffmpeg, path, head, cancel=cancel, timeout_s=self.decode_timeout_s
                    ),
                    "tail": alg.frame_hashes(
                        ffmpeg, path, tail, cancel=cancel, timeout_s=self.decode_timeout_s
                    ),
                }
            if "audio" in kinds:
                out["audio"] = {
                    "rate_hz": alg.ENVELOPE_RATE_HZ,
                    "window_ms": alg.WINDOW_MS,
                    "head_start_ms": head.start_ms,
                    "head": alg.audio_envelope(
                        ffmpeg, path, head, cancel=cancel, timeout_s=self.decode_timeout_s
                    ),
                    "tail_start_ms": tail.start_ms,
                    "tail": alg.audio_envelope(
                        ffmpeg, path, tail, cancel=cancel, timeout_s=self.decode_timeout_s
                    ),
                }
        return out

    # -- candidates -------------------------------------------------------------------

    @staticmethod
    def _candidate_ids(conn: sqlite3.Connection, asset_id: str) -> list[str]:
        rows = DuplicateCandidateRepository(conn).query(
            asset_id=asset_id, limit=MAX_CANDIDATES_PER_ASSET
        )
        return [r.asset_b if r.asset_a == asset_id else r.asset_a for r in rows]

    def find_candidates(self, conn: sqlite3.Connection, asset_id: str) -> list[str]:
        """Compare an asset's frames with every asset of similar duration; record matches.

        Returns the assets that became candidates for the first time.
        """
        assets = AssetRepository(conn)
        prints = FingerprintRepository(conn)
        asset = assets.get(asset_id)
        mine = prints.for_asset(asset_id)
        frames = mine.get("frames")
        if not is_current(frames, "frames") or frames is None:
            return []
        duration = asset.duration_ms
        slack = max(alg.MATCH_DURATION_SLACK_MS, int(alg.MATCH_DURATION_RATIO * duration) + 1)
        audio = mine.get("audio")
        found: list[str] = []
        for other_id in assets.ids_with_duration(
            duration - slack, duration + slack, exclude=asset_id
        ):
            theirs = prints.for_asset(other_id)
            other_frames = theirs.get("frames")
            if not is_current(other_frames, "frames") or other_frames is None:
                continue
            other_duration = assets.get(other_id).duration_ms
            match = alg.compare_frames(frames.data, other_frames.data, duration, other_duration)
            if match is None:
                continue
            evidence = dict(match.evidence)
            other_audio = theirs.get("audio")
            if (
                audio is not None
                and other_audio is not None
                and is_current(audio, "audio")
                and is_current(other_audio, "audio")
            ):
                corr = alg.correlation(audio.data["head"], other_audio.data["head"])
                if corr is not None:
                    evidence["audio_correlation"] = corr
            with transaction(conn):
                _, created = DuplicateCandidateRepository(conn).record(
                    asset_id,
                    other_id,
                    score=match.score,
                    evidence=evidence,
                    algorithm=alg.MATCH_ALGORITHM,
                    version=alg.MATCH_VERSION,
                )
            if created:
                found.append(other_id)
        return found

    # -- backfill ---------------------------------------------------------------------

    def backfill(
        self, params: Mapping[str, Any], *, cancel: threading.Event, progress: Progress
    ) -> dict[str, Any]:
        """The ``fingerprint`` job: compute missing or stale fingerprints asset by asset."""
        self.ffmpeg()  # fail early and clearly, before touching anything
        force = bool(params.get("force", False))
        counts = dict.fromkeys(
            ("updated", "up_to_date", "unavailable", "failed", "new_candidates"), 0
        )
        with contextlib.closing(self.database.connect()) as conn:
            requested = params.get("asset_ids")
            ids = list(requested) if requested else AssetRepository(conn).ids()
            total = len(ids)
            for i, asset_id in enumerate(ids, start=1):
                if cancel.is_set():
                    raise FingerprintCancelled
                try:
                    outcome = self.fingerprint_asset(conn, asset_id, cancel=cancel, force=force)
                except NotFoundError:
                    outcome = AssetOutcome("unavailable")
                counts[outcome.status] += 1
                counts["new_candidates"] += len(outcome.new_candidates)
                progress(i, total, f"{i} of {total} assets")
        result = FingerprintResult.model_validate({"considered": total, **counts})
        if total:
            progress(total, total, summary(counts))  # the job's final message
        return result.model_dump(mode="json")


def summary(result: Mapping[str, int]) -> str:
    parts = [
        (result["updated"], "updated"),
        (result["up_to_date"], "up to date"),
        (result["unavailable"], "unavailable"),
        (result["failed"], "failed"),
        (result["new_candidates"], "new duplicate candidates"),
    ]
    return ", ".join(f"{n} {label}" for n, label in parts if n) or "No assets"
