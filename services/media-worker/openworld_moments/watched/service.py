# SPDX-License-Identifier: AGPL-3.0-or-later
"""Watched folders on the worker side (M07): configuration, file records, and the
decision whether a stable file reported by the host should be imported.

The host watches the folder and reports a file only after its size and
modification time stayed unchanged for the stabilization period. The worker
remembers the latest version of each file it was told about and the import job
it started for it, so repeated events, rescans, and restarts never import the
same version twice. A changed version (new size or mtime) is imported again;
identical bytes still resolve to the existing asset (M05). Nothing here moves,
renames, or deletes a watched file.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.watched_folder_schema import (
    WatchedFile,
    WatchedFileDecision,
)

from openworld_moments.jobs.engine import ACTIVE
from openworld_moments.media.probe import check_path_param
from openworld_moments.storage import (
    JobRepository,
    NotFoundError,
    WatchedFileRow,
    WatchedFolderRepository,
    WatchedFolderRow,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION
from openworld_moments.watched.patterns import is_candidate, validate_patterns

SOURCE_KINDS = ("xbox", "playstation", "obs", "capture_card", "phone_upload", "other")
MODES = ("reference", "managed")
#: Retryable import failures of one file version are retried this many times in all...
MAX_ATTEMPTS = 5
#: ...waiting RETRY_BASE_S x 2^(attempt-1) after each failure, at most RETRY_MAX_S.
RETRY_BASE_S = 60
RETRY_MAX_S = 3600
_RETRYABLE_STATES = frozenset({"cancelled"})


class WatchError(Exception):
    """A request about watched folders is refused. ``status`` maps to HTTP."""

    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# -- validation -----------------------------------------------------------------------


def _choice(body: Mapping[str, Any], key: str, options: tuple[str, ...]) -> str:
    value = body[key]
    if value not in options:
        raise WatchError("watch.invalid_request", f"'{key}' must be one of {', '.join(options)}")
    return str(value)


def _flag(body: Mapping[str, Any], key: str) -> bool:
    value = body[key]
    if not isinstance(value, bool):
        raise WatchError("watch.invalid_request", f"'{key}' must be true or false")
    return value


def validate_changes(body: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
    """Normalize a WatchedFolderRequest. Raises WatchError."""
    allowed = {"source_kind", "mode", "recursive", "include", "exclude", "enabled"}
    if creating:
        allowed.add("path")
    unknown = set(body) - allowed
    if unknown:
        raise WatchError("watch.invalid_request", f"unknown field(s): {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    if creating:
        try:
            path = check_path_param(body.get("path"))
        except ValueError as exc:
            raise WatchError("watch.invalid_request", str(exc)) from exc
        if not Path(path).is_dir():
            raise WatchError("watch.not_a_folder", "The path is not a folder that can be read.")
        clean["path"] = path
    if "source_kind" in body:
        clean["source_kind"] = _choice(body, "source_kind", SOURCE_KINDS)
    if "mode" in body:
        clean["mode"] = _choice(body, "mode", MODES)
    for key in ("recursive", "enabled"):
        if key in body:
            clean[key] = _flag(body, key)
    for key in ("include", "exclude"):
        if key in body:
            try:
                clean[key] = validate_patterns(body[key], key)
            except ValueError as exc:
                raise WatchError("watch.invalid_request", str(exc)) from exc
    return clean


def resolve(folder: WatchedFolderRow, relative_path: str) -> Path:
    """The absolute path of a reported file. Refuses anything that could leave the folder."""
    if not relative_path or "\\" in relative_path or "\0" in relative_path:
        raise WatchError("watch.invalid_path", "Relative paths use '/' and cannot be empty.")
    rel = PurePosixPath(relative_path)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in relative_path.split("/")):
        raise WatchError("watch.invalid_path", "The path must stay inside the watched folder.")
    if ":" in rel.parts[0]:  # 'C:...' would be absolute on Windows
        raise WatchError("watch.invalid_path", "The path must stay inside the watched folder.")
    if not folder.recursive and len(rel.parts) > 1:
        raise WatchError("watch.invalid_path", "This folder does not include subfolders.")
    return Path(folder.path).joinpath(*rel.parts)


# -- state ----------------------------------------------------------------------------


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _format(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def retry_at(attempts: int, failed_at: str) -> str:
    delay = min(RETRY_MAX_S, RETRY_BASE_S * 2 ** (attempts - 1))
    return _format(_parse(failed_at) + timedelta(seconds=delay))


def file_state(conn: sqlite3.Connection, row: WatchedFileRow) -> dict[str, Any]:
    """Derive a file's state from its import job.

    ``state``: queued | in_progress | imported | failed. Also ``asset_id``, ``error``,
    ``retryable`` (whether another attempt will be made), and ``retry_at``.
    """
    out: dict[str, Any] = {"state": "imported", "retryable": False}
    if row.job_id is None:
        return out
    try:
        job = JobRepository(conn).get(row.job_id)
    except NotFoundError:
        return out  # pruned: it finished long ago
    if job.state == "queued":
        out["state"] = "queued"
    elif job.state in ACTIVE:
        out["state"] = "in_progress"
    elif job.state == "ready":
        result = job.result or {}
        items = result.get("items") or [{}]
        if items[0].get("asset_id"):
            out["asset_id"] = items[0]["asset_id"]
    else:
        out["state"] = "failed"
        if job.error is not None:
            out["error"] = normalize(job.error)
            retryable = bool(job.error.retryable)
        else:
            out["error"] = {
                "code": "job.cancelled",
                "message": "The import was cancelled.",
                "retryable": True,
            }
            retryable = job.state in _RETRYABLE_STATES
        if retryable and row.attempts < MAX_ATTEMPTS:
            out["retryable"] = True
            out["retry_at"] = retry_at(row.attempts, job.finished_at or row.updated_at)
    return out


def file_doc(conn: sqlite3.Connection, row: WatchedFileRow) -> dict[str, Any]:
    state = file_state(conn, row)
    doc: dict[str, Any] = {
        "relative_path": row.relative_path,
        "size_bytes": row.size_bytes,
        "mtime_ns": row.mtime_ns,
        "state": state["state"],
        "attempts": row.attempts,
        "updated_at": row.updated_at,
    }
    for key in ("asset_id", "error", "retry_at"):
        if key in state:
            doc[key] = state[key]
    if row.job_id:
        doc["job_id"] = row.job_id
    return normalize(WatchedFile.model_validate(doc))


def folder_doc(conn: sqlite3.Connection, folder: WatchedFolderRow) -> dict[str, Any]:
    stats = {"tracked": 0, "imported": 0, "in_progress": 0, "failed": 0}
    for job_id, state in WatchedFolderRepository(conn).job_states(folder.id):
        stats["tracked"] += 1
        if job_id is None or state is None or state == "ready":
            stats["imported"] += 1
        elif state == "queued" or state in ACTIVE:
            stats["in_progress"] += 1
        else:
            stats["failed"] += 1
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "id": folder.id,
        "path": folder.path,
        "source_kind": folder.source_kind,
        "mode": folder.mode,
        "recursive": folder.recursive,
        "include": folder.include,
        "exclude": folder.exclude,
        "enabled": folder.enabled,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
        "availability": folder.availability,
        "stats": stats,
    }
    if folder.last_scan_at:
        doc["last_scan_at"] = folder.last_scan_at
    if folder.last_error:
        doc["last_error"] = folder.last_error
    return normalize(load("watched-folder", doc))


# -- reports --------------------------------------------------------------------------


def idempotency_key(
    folder_id: int, relative_path: str, size: int, mtime_ns: int, attempt: int
) -> str:
    digest = hashlib.sha256(f"{relative_path}\0{size}\0{mtime_ns}".encode()).hexdigest()[:32]
    return f"watch:{folder_id}:{digest}:{attempt}"


def validate_report(body: Mapping[str, Any]) -> tuple[str, int, int]:
    unknown = set(body) - {"relative_path", "size_bytes", "mtime_ns"}
    if unknown:
        raise WatchError("watch.invalid_request", f"unknown field(s): {', '.join(sorted(unknown))}")
    rel, size, mtime = body.get("relative_path"), body.get("size_bytes"), body.get("mtime_ns")
    if not isinstance(rel, str) or not 1 <= len(rel) <= 4096:
        raise WatchError("watch.invalid_request", "'relative_path' must be 1 to 4096 characters")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise WatchError("watch.invalid_request", "'size_bytes' must be a positive integer")
    if isinstance(mtime, bool) or not isinstance(mtime, int):
        raise WatchError("watch.invalid_request", "'mtime_ns' must be an integer")
    return rel, size, mtime


def decide(
    conn: sqlite3.Connection, folder: WatchedFolderRow, rel: str, size: int, mtime_ns: int
) -> tuple[int | None, dict[str, Any]]:
    """``(attempt, decision)``: an attempt number when an import should be submitted,
    otherwise None and the final WatchedFileDecision."""
    if not folder.enabled:
        raise WatchError("watch.folder_disabled", "The folder is disabled.", status=409)
    resolve(folder, rel)
    if not is_candidate(rel, folder.include, folder.exclude):
        return None, {"action": "ignored"}
    record = WatchedFolderRepository(conn).file(folder.id, rel)
    if record is None or (record.size_bytes, record.mtime_ns) != (size, mtime_ns):
        return 1, {}
    state = file_state(conn, record)
    if state["state"] in ("queued", "in_progress"):
        return None, _decision("in_progress", record.job_id)
    if state["state"] == "imported" or not state["retryable"]:
        return None, _decision("known", record.job_id)
    if utc_now() < state["retry_at"]:
        return None, {**_decision("backoff", record.job_id), "retry_at": state["retry_at"]}
    return record.attempts + 1, {}


def _decision(action: str, job_id: str | None) -> dict[str, Any]:
    doc: dict[str, Any] = {"action": action}
    if job_id:
        doc["job_id"] = job_id
    return normalize(WatchedFileDecision.model_validate(doc))


def import_params(folder: WatchedFolderRow, rel: str) -> dict[str, Any]:
    return {
        "paths": [str(resolve(folder, rel))],
        "mode": folder.mode,
        "recursive": False,
        "source_kind": folder.source_kind,
    }


def record_submission(
    conn: sqlite3.Connection,
    folder: WatchedFolderRow,
    rel: str,
    size: int,
    mtime_ns: int,
    attempt: int,
    job_id: str,
) -> dict[str, Any]:
    WatchedFolderRepository(conn).save_file(
        WatchedFileRow(
            folder_id=folder.id,
            relative_path=rel,
            size_bytes=size,
            mtime_ns=mtime_ns,
            attempts=attempt,
            job_id=job_id,
            updated_at=utc_now(),
        )
    )
    return _decision("queued", job_id)


def scan_error(body: Mapping[str, Any]) -> tuple[bool, bool, dict[str, Any] | None]:
    unknown = set(body) - {"available", "scanned", "error"}
    if unknown:
        raise WatchError("watch.invalid_request", f"unknown field(s): {', '.join(sorted(unknown))}")
    available, scanned = body.get("available"), body.get("scanned", False)
    if not isinstance(available, bool) or not isinstance(scanned, bool):
        raise WatchError("watch.invalid_request", "'available' and 'scanned' must be true or false")
    error = body.get("error")
    if error is not None:
        if not isinstance(error, dict):
            raise WatchError("watch.invalid_request", "'error' must be an ErrorInfo object")
        try:
            error = normalize(load("error", error))
        except Exception as exc:  # contract violation in a host report
            raise WatchError(
                "watch.invalid_request", "'error' must be an ErrorInfo object"
            ) from exc
    return available, scanned, error
