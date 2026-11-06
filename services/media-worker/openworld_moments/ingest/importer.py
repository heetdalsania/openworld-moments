# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import batches, relinking, and the missing-source check (M05).

Per file, in order (see docs/architecture/import.md):

1. pre-check (regular, non-empty, readable, within the size limit);
2. probe with FFprobe (M04): anything that is not usable video stops here, so
   unsupported media never reaches managed storage or the database;
3. hash it: in place (reference) or while copying into staging (managed),
   verifying the source did not change since it was probed;
4. managed only: move the staged copy into ``managed-media/`` atomically;
5. one transaction: the asset row (or the existing asset with the same SHA-256)
   plus a provenance row.

Repeating an import is safe: identical bytes resolve to the existing asset and
only its provenance ``last_seen_at`` changes.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.import_schema import RelinkResult, SourceCheckResult
from openworld_moments_contracts.generated.media_asset_schema import MediaAsset

from openworld_moments.fingerprints import algorithms as fp_alg
from openworld_moments.fingerprints.service import (
    CURRENT,
    FingerprintCancelled,
    Fingerprinter,
    FingerprintFailure,
    is_current,
)
from openworld_moments.ids import new_id
from openworld_moments.ingest.files import (
    FileStepError,
    Fingerprint,
    ImportCancelled,
    Staged,
    hash_file,
    promote,
    snapshot,
    stage_copy,
)
from openworld_moments.ingest.library import LibraryPaths
from openworld_moments.ingest.scan import Candidate, Problem, ScanTooLarge, scan
from openworld_moments.media.probe import (
    DEFAULT_TIMEOUT_S,
    ProbeCancelled,
    ProbeError,
    precheck,
    probe_file,
)
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import (
    AssetImportRepository,
    AssetRepository,
    ConflictError,
    Database,
    FingerprintRepository,
    NotFoundError,
    StoredFingerprint,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

Mode = Literal["reference", "managed"]
Progress = Callable[[int, int, str], None]
SetState = Callable[[str], None]
ReportFor = Callable[[int], Callable[[int], None]]
#: Seconds between byte-progress updates while hashing or copying one large file.
BYTE_PROGRESS_INTERVAL_S = 0.5

#: Largest file one import accepts. Far above any console capture; stops absurd inputs.
MAX_FILE_BYTES = 1 << 40  # 1 TiB
#: Free space kept in reserve beyond the file itself when copying into the library.
FREE_SPACE_MARGIN = 256 * 1024 * 1024
MAX_MISSING_IDS = 1000
#: Capture-time confidence by basis. Preliminary; session grouping (M11) refines it.
CONTAINER_TIME_CONFIDENCE = 0.6
MTIME_CONFIDENCE = 0.2


class ImportFailure(Exception):
    """A whole job fails. Carries the contract ErrorInfo fields and an optional result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, str | int | float | bool | None] | None = None,
        stderr_tail: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details) if details else None
        self.stderr_tail = stderr_tail or None
        self.result = result


class _ItemError(Exception):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error["message"])
        self.error = error


def _error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: Mapping[str, Any] | None = None,
    stderr_tail: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if details:
        error["details"] = dict(details)
    if stderr_tail:
        error["stderr_tail"] = stderr_tail[-8192:]
    return error


def _from_probe(exc: ProbeError) -> dict[str, Any]:
    return _error(
        exc.code,
        exc.message,
        retryable=exc.retryable,
        details=exc.details,
        stderr_tail=exc.stderr_tail,
    )


def _from_step(exc: FileStepError) -> dict[str, Any]:
    return _error(exc.code, exc.message, retryable=exc.retryable)


def _require_ffprobe(tools: MediaTools) -> ToolInfo:
    ffprobe = tools.tool("ffprobe")
    if not ffprobe.ok:
        code = (
            "tool.ffprobe_missing"
            if ffprobe.status == "missing"
            else (f"tool.ffprobe_{ffprobe.status}")
        )
        raise ImportFailure(
            code,
            f"FFprobe is not usable: {ffprobe.problem}. Install FFmpeg 6.0 or newer, "
            "or set OWM_FFPROBE.",
            retryable=True,
        )
    return ffprobe


def capture_time(probe: Mapping[str, Any], mtime_ns: int) -> dict[str, Any]:
    """Preliminary capture-time estimate: container creation time, else file mtime."""
    created = probe.get("creation_time")
    if created:
        return {
            "captured_at": created,
            "confidence": CONTAINER_TIME_CONFIDENCE,
            "basis": ["container_metadata"],
        }
    when = datetime.fromtimestamp(mtime_ns / 1e9, tz=UTC)
    return {
        "captured_at": when.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "confidence": MTIME_CONFIDENCE,
        "basis": ["filesystem_mtime"],
    }


@dataclass
class _Batch:
    mode: Mode
    source_kind: str
    job_id: str
    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, entry: Candidate | Problem, outcome: str, **extra: Any) -> None:
        item: dict[str, Any] = {"source": entry.source, "outcome": outcome, **extra}
        if entry.relative_path is not None:
            item["relative_path"] = entry.relative_path
        self.items.append(item)

    def result(self) -> dict[str, Any]:
        totals = dict.fromkeys(("imported", "existing", "relinked", "skipped", "failed"), 0)
        for item in self.items:
            totals[item["outcome"]] += 1
        doc = {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "totals": {"files": len(self.items), **totals},
            "items": self.items,
        }
        return normalize(load("import", doc))


def summary(totals: Mapping[str, int]) -> str:
    parts = [
        (totals["imported"], "imported"),
        (totals["existing"], "already in the library"),
        (totals["relinked"], "relinked"),
        (totals["skipped"], "skipped"),
        (totals["failed"], "failed"),
    ]
    return ", ".join(f"{n} {label}" for n, label in parts if n) or "Nothing to import"


class Importer:
    """Runs on a job's worker thread with its own database connection."""

    def __init__(
        self,
        database: Database,
        tools: MediaTools,
        *,
        library: LibraryPaths | None = None,
        max_file_bytes: int = MAX_FILE_BYTES,
        probe_timeout_s: float = DEFAULT_TIMEOUT_S,
        free_space_margin: int = FREE_SPACE_MARGIN,
    ) -> None:
        self.database = database
        self.tools = tools
        self.library = library or LibraryPaths.for_database(database.path)
        self.max_file_bytes = max_file_bytes
        self.probe_timeout_s = probe_timeout_s
        self.free_space_margin = free_space_margin
        self.fingerprinter = Fingerprinter(database, tools, library=self.library)

    # -- import -----------------------------------------------------------------------

    def run_import(
        self,
        params: Mapping[str, Any],
        *,
        job_id: str,
        cancel: threading.Event,
        progress: Progress,
        set_state: SetState | None = None,
    ) -> dict[str, Any]:
        """Import a batch. Returns the ImportResult, or raises ImportFailure (with the
        result attached) when nothing could be imported, or ImportCancelled.

        New assets are fingerprinted afterwards (state ``fingerprinting``); look-alike
        assets are reported per item as ``candidate_asset_ids``."""
        ffprobe = _require_ffprobe(self.tools)
        try:
            entries = scan(params["paths"], recursive=bool(params.get("recursive", False)))
        except ScanTooLarge as exc:
            raise ImportFailure(
                "import.too_many_files",
                "The selection contains more files than one import allows (10,000). "
                "Import smaller folders.",
            ) from exc
        batch = _Batch(params["mode"], params.get("source_kind", "other"), job_id)
        candidates = sum(isinstance(e, Candidate) for e in entries)
        staging = self.library.job_staging(job_id)
        self.library.clean_import_staging(job_id)  # leftovers of an interrupted attempt
        done = 0
        new_assets: list[tuple[int, str]] = []
        if candidates:
            progress(0, candidates, f"0 of {candidates} files")
        conn = self.database.connect()
        try:
            for entry in entries:
                if isinstance(entry, Problem):
                    batch.add(
                        entry,
                        entry.outcome,
                        error=_error(entry.code, entry.message, retryable=entry.retryable),
                    )
                    continue
                if cancel.is_set():
                    raise ImportCancelled
                report_for = self._byte_progress(progress, done, candidates)
                try:
                    outcome, asset_id = self._import_one(
                        conn, entry, batch, ffprobe, staging, cancel, report_for
                    )
                except _ItemError as exc:
                    batch.add(entry, "failed", error=exc.error)
                else:
                    batch.add(entry, outcome, asset_id=asset_id)
                    if outcome in ("imported", "relinked"):
                        new_assets.append((len(batch.items) - 1, asset_id))
                done += 1
                progress(done, candidates, f"{done} of {candidates} files")
            if new_assets:
                if set_state is not None:
                    set_state("fingerprinting")
                self._fingerprint_new(conn, batch, new_assets, cancel, progress)
        finally:
            conn.close()
            self.library.clean_import_staging(job_id)
        result = batch.result()
        totals = result["totals"]
        if candidates:  # the job's final message: what happened, never file names
            progress(candidates, candidates, summary(totals))
        if candidates == 0:
            raise ImportFailure(
                "import.no_media_found",
                "No supported video files were found.",
                details={"skipped": totals["skipped"], "failed": totals["failed"]},
                result=result,
            )
        if totals["imported"] + totals["existing"] + totals["relinked"] == 0:
            failed = [i["error"] for i in result["items"] if i["outcome"] == "failed"]
            if len(failed) == 1:
                only = failed[0]
                raise ImportFailure(
                    only["code"],
                    only["message"],
                    retryable=only["retryable"],
                    details=only.get("details"),
                    stderr_tail=only.get("stderr_tail"),
                    result=result,
                )
            raise ImportFailure(
                "import.all_failed",
                f"None of the {len(failed)} files could be imported.",
                retryable=any(e["retryable"] for e in failed),
                details={"failed": len(failed)},
                result=result,
            )
        return result

    @staticmethod
    def _byte_progress(progress: Progress, done: int, total: int) -> ReportFor:
        """For one file of ``size`` bytes: a callback posting throttled
        'File N of M: P%' messages while it is hashed or copied."""

        def report_for(size: int) -> Callable[[int], None]:
            last = [time.monotonic()]

            def on_bytes(read: int) -> None:
                now = time.monotonic()
                if size <= 0 or now - last[0] < BYTE_PROGRESS_INTERVAL_S:
                    return
                last[0] = now
                progress(done, total, f"File {done + 1} of {total}: {min(99, read * 100 // size)}%")

            return on_bytes

        return report_for

    def _fingerprint_new(
        self,
        conn: sqlite3.Connection,
        batch: _Batch,
        new_assets: list[tuple[int, str]],
        cancel: threading.Event,
        progress: Progress,
    ) -> None:
        """Fingerprint newly imported assets and attach their duplicate candidates.

        Best effort: a decode failure or a missing FFmpeg never fails the import;
        the ``fingerprint`` backfill job fills the gap later.
        """
        total = len(new_assets)
        for k, (index, asset_id) in enumerate(new_assets, start=1):
            progress(k - 1, total, f"Fingerprinting {k} of {total}")
            try:
                outcome = self.fingerprinter.fingerprint_asset(conn, asset_id, cancel=cancel)
            except FingerprintCancelled as exc:
                raise ImportCancelled from exc
            except FingerprintFailure:
                return  # FFmpeg unusable: skip the rest; backfill later
            if outcome.candidates:
                batch.items[index]["candidate_asset_ids"] = outcome.candidates[:20]
        progress(total, total, f"Fingerprinted {total} of {total}")

    def _without_copy(
        self,
        conn: sqlite3.Connection,
        path: Path,
        fast: str,
        before: os.stat_result,
        cancel: threading.Event,
        on_bytes: Callable[[int], None],
    ) -> Fingerprint | None:
        """Managed mode: if the fast hash says these bytes may already be in the library,
        confirm with the full SHA-256 in place and skip the copy. Returns None when a
        copy is needed (no match, or the match is a lost managed copy to restore)."""
        assets = AssetRepository(conn)
        if not assets.ids_by_fast_hash(fast, before.st_size):
            return None
        fingerprint = hash_file(path, cancel=cancel, expected=before, on_bytes=on_bytes)
        existing = assets.find_by_sha256(fingerprint.sha256)
        if existing is None:
            return None  # a fast-hash collision: different bytes
        location = assets.location(existing.id)
        if location.missing_at is not None and location.import_mode == "managed":
            return None
        return fingerprint

    def _import_one(
        self,
        conn: sqlite3.Connection,
        entry: Candidate,
        batch: _Batch,
        ffprobe: ToolInfo,
        staging: Path,
        cancel: threading.Event,
        report_for: ReportFor,
    ) -> tuple[str, str]:
        path = entry.path
        try:
            before = snapshot(path)
            precheck(path)
            if before.st_size > self.max_file_bytes:
                raise _ItemError(
                    _error(
                        "import.file_too_large",
                        f"The file is larger than the {self.max_file_bytes} byte import limit.",
                    )
                )
            probe = probe_file(path, ffprobe, timeout_s=self.probe_timeout_s, cancel=cancel)
            try:
                fast = fp_alg.fast_hash(path, before.st_size)
            except OSError as exc:
                raise FileStepError(
                    "media.unreadable", f"The file cannot be read: {exc.strerror}.", retryable=True
                ) from exc
            report = report_for(before.st_size)
            staged: Staged | None = None
            reused = None
            if batch.mode == "managed":
                reused = self._without_copy(conn, path, fast, before, cancel, report)
            if reused is not None:
                fingerprint = reused
            elif batch.mode == "managed":
                self._check_free_space(before.st_size)
                staged = stage_copy(path, staging, cancel=cancel, expected=before, on_bytes=report)
                fingerprint = staged.fingerprint
            else:
                fingerprint = hash_file(path, cancel=cancel, expected=before, on_bytes=report)
        except ProbeCancelled as exc:
            raise ImportCancelled from exc
        except ProbeError as exc:
            raise _ItemError(_from_probe(exc)) from exc
        except FileStepError as exc:
            raise _ItemError(_from_step(exc)) from exc
        try:
            return self._commit(conn, entry, batch, probe, fingerprint, staged, fast)
        finally:
            if staged is not None:
                staged.path.unlink(missing_ok=True)

    def _check_free_space(self, size: int) -> None:
        try:
            free = shutil.disk_usage(self.library.root).free
        except OSError:
            return  # unknown: the copy itself reports a full disk
        if free < size + self.free_space_margin:
            raise _ItemError(
                _error(
                    "import.disk_full",
                    "Not enough free space in the library for this file.",
                    retryable=True,
                    details={"required_bytes": size + self.free_space_margin, "free_bytes": free},
                )
            )

    def _place(self, staged: Staged, extension: str) -> str:
        relpath = self.library.managed_relpath(staged.fingerprint.sha256, extension)
        target = self.library.resolve_managed(relpath)
        if target is None:  # pragma: no cover - relpath is built here
            raise _ItemError(_error("import.write_failed", "Invalid library path."))
        try:
            promote(staged, target)
        except FileStepError as exc:
            raise _ItemError(_from_step(exc)) from exc
        return relpath

    def _commit(
        self,
        conn: sqlite3.Connection,
        entry: Candidate,
        batch: _Batch,
        probe: Mapping[str, Any],
        fingerprint: Fingerprint,
        staged: Staged | None,
        fast: str,
    ) -> tuple[str, str]:
        path = entry.path
        extension = path.suffix.lower()
        for _attempt in range(2):  # a second pass only after losing an insert race
            try:
                with transaction(conn):
                    assets = AssetRepository(conn)
                    existing = assets.find_by_sha256(fingerprint.sha256)
                    if existing is not None:
                        asset_id = existing.id
                        outcome = self._existing(
                            assets, asset_id, batch.mode, path, staged, extension
                        )
                    else:
                        # Promote before the row exists, so a row never names a missing
                        # file. A crash in between leaves an unreferenced, complete copy
                        # that the next import of the same bytes adopts.
                        managed_path = self._place(staged, extension) if staged else None
                        asset_id = new_id("ast")
                        asset = self._asset(asset_id, path, batch, probe, fingerprint, fast)
                        assets.add(asset, original_path=str(path), managed_path=managed_path)
                        outcome = "imported"
                    self._record_fast(conn, asset_id, fast)
                    AssetImportRepository(conn).record(
                        asset_id=asset_id,
                        import_mode=batch.mode,
                        source_kind=batch.source_kind,
                        source_path=str(path),
                        size_bytes=fingerprint.size,
                        mtime_ns=fingerprint.mtime_ns,
                        job_id=batch.job_id,
                    )
            except ConflictError:
                continue  # the same bytes were committed concurrently: resolve as existing
            return outcome, asset_id
        raise _ItemError(  # pragma: no cover - needs two lost races in a row
            _error("import.conflict", "The asset changed concurrently; retry.", retryable=True)
        )

    @staticmethod
    def _record_fast(conn: sqlite3.Connection, asset_id: str, fast: str) -> None:
        """Store the fast hash computed during import, unless a current one exists."""
        prints = FingerprintRepository(conn)
        if is_current(prints.for_asset(asset_id).get("fast"), "fast"):
            return
        algorithm, version = CURRENT["fast"]
        prints.put(
            StoredFingerprint(
                asset_id=asset_id,
                kind="fast",
                algorithm=algorithm,
                version=version,
                data={"value": fast},
                computed_at=utc_now(),
            )
        )
        AssetRepository(conn).set_fast_hash(asset_id, fast)

    def _existing(
        self,
        assets: AssetRepository,
        asset_id: str,
        mode: Mode,
        path: Path,
        staged: Staged | None,
        extension: str,
    ) -> str:
        """Same bytes already imported. Restore a missing asset when this import can."""
        location = assets.location(asset_id)
        if location.missing_at is None:
            return "existing"
        if location.import_mode == "reference" and mode == "reference":
            assets.set_original_path(asset_id, str(path))
            return "relinked"
        if location.import_mode == "managed" and staged is not None:
            relpath = location.managed_path or self.library.managed_relpath(
                staged.fingerprint.sha256, extension
            )
            target = self.library.resolve_managed(relpath)
            if target is None:
                return "existing"
            try:
                promote(staged, target)
            except FileStepError as exc:
                raise _ItemError(_from_step(exc)) from exc
            assets.clear_missing(asset_id)
            return "relinked"
        return "existing"

    def _asset(
        self,
        asset_id: str,
        path: Path,
        batch: _Batch,
        probe: Mapping[str, Any],
        fingerprint: Fingerprint,
        fast: str,
    ) -> MediaAsset:
        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": asset_id,
            "sha256": fingerprint.sha256,
            "fast_hash": fast,
            "original_name": path.name[:1024],
            "source_kind": batch.source_kind,
            "import_mode": batch.mode,
            "size_bytes": fingerprint.size,
            "capture_time": capture_time(probe, fingerprint.mtime_ns),
            "duration_ms": probe["duration_ms"],
            "container": probe["container"],
            "audio": probe["audio"],
            "created_at": utc_now(),
        }
        if "video" in probe:
            doc["video"] = probe["video"]
        return load("media-asset", doc)  # type: ignore[return-value]

    # -- relink -----------------------------------------------------------------------

    def verify_identity(
        self,
        sha256: str,
        size: int | None,
        path: Path,
        *,
        cancel: threading.Event,
        fast: str | None = None,
    ) -> Fingerprint:
        """Is ``path`` the asset's content? Size, then the fast hash (2 MiB read) when the
        asset has a current one, then the full SHA-256, which alone decides a match."""
        before = snapshot(path)
        if size is not None and before.st_size != size:
            raise ImportFailure(
                "relink.identity_mismatch",
                "The selected file is not the original: its size differs.",
            )
        if fast is not None:
            try:
                candidate_fast = fp_alg.fast_hash(path, before.st_size)
            except OSError as exc:
                raise ImportFailure(
                    "media.unreadable", f"The file cannot be read: {exc.strerror}.", retryable=True
                ) from exc
            if candidate_fast != fast:
                raise ImportFailure(
                    "relink.identity_mismatch",
                    "The selected file is not the original: its content differs.",
                )
        fingerprint = hash_file(path, cancel=cancel, expected=before)
        if fingerprint.sha256 != sha256:
            raise ImportFailure(
                "relink.identity_mismatch",
                "The selected file is not the original: its content differs.",
            )
        return fingerprint

    def relink(
        self, params: Mapping[str, Any], *, job_id: str, cancel: threading.Event
    ) -> dict[str, Any]:
        asset_id: str = params["asset_id"]
        path = Path(params["path"])
        with contextlib.closing(self.database.connect()) as conn:
            assets = AssetRepository(conn)
            try:
                asset = assets.get(asset_id)
                location = assets.location(asset_id)
            except NotFoundError as exc:
                raise ImportFailure("asset.not_found", "The asset does not exist.") from exc
            if location.import_mode != "reference":
                raise ImportFailure(
                    "relink.not_referenced",
                    "Only referenced assets can be relinked. Import the file again in "
                    "managed mode to restore a library copy.",
                )
            try:
                precheck(path)
                stored_fast = FingerprintRepository(conn).for_asset(asset_id).get("fast")
                fingerprint = self.verify_identity(
                    asset.sha256,
                    location.size_bytes,
                    path,
                    cancel=cancel,
                    fast=stored_fast.data["value"]
                    if is_current(stored_fast, "fast") and stored_fast is not None
                    else None,
                )
            except ProbeError as exc:
                raise ImportFailure(exc.code, exc.message, retryable=exc.retryable) from exc
            except FileStepError as exc:
                raise ImportFailure(exc.code, exc.message, retryable=exc.retryable) from exc
            with transaction(conn):
                assets.set_original_path(asset_id, str(path))
                AssetImportRepository(conn).record(
                    asset_id=asset_id,
                    import_mode="reference",
                    source_kind=str(asset.source_kind),
                    source_path=str(path),
                    size_bytes=fingerprint.size,
                    mtime_ns=fingerprint.mtime_ns,
                    job_id=job_id,
                )
        return RelinkResult(asset_id=asset_id, verified_by="sha256").model_dump(mode="json")

    # -- missing sources --------------------------------------------------------------

    def _available(self, path: Path | None, size: int | None) -> bool:
        if path is None:
            return False
        try:
            info = path.stat()
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and (size is None or info.st_size == size)

    def check_sources(self, *, cancel: threading.Event, progress: Progress) -> dict[str, Any]:
        """Mark assets whose bytes are gone as missing, and clear the mark when they are
        back. A referenced file whose size changed counts as missing: it was replaced."""
        with contextlib.closing(self.database.connect()) as conn:
            locations = AssetRepository(conn).locations()
            total = len(locations)
            newly: list[str] = []
            restored: list[str] = []
            missing: list[str] = []
            for i, location in enumerate(locations, start=1):
                if cancel.is_set():
                    raise ImportCancelled
                if location.import_mode == "managed":
                    path = (
                        self.library.resolve_managed(location.managed_path)
                        if location.managed_path
                        else None
                    )
                else:
                    path = Path(location.original_path) if location.original_path else None
                ok = self._available(path, location.size_bytes)
                if not ok:
                    missing.append(location.id)
                    if location.missing_at is None:
                        newly.append(location.id)
                elif location.missing_at is not None:
                    restored.append(location.id)
                if i % 100 == 0 or i == total:
                    progress(i, total, f"{i} of {total} assets checked")
            now = utc_now()
            with transaction(conn):
                assets = AssetRepository(conn)
                for asset_id in newly:
                    assets.mark_missing(asset_id, now)
                for asset_id in restored:
                    assets.clear_missing(asset_id)
        return SourceCheckResult.model_validate(
            {
                "checked": total,
                "missing": len(missing),
                "newly_missing": len(newly),
                "restored": len(restored),
                "missing_asset_ids": missing[:MAX_MISSING_IDS],
            }
        ).model_dump(mode="json")
