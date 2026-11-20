# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streaming hashing, staged copies, and atomic promotion.

Sources are only ever opened read-only. A source counts as stable only if its
size and modification time are identical before and after it was read, and
the number of bytes read equals that size; otherwise the file is still being
written (e.g. by OneDrive) and the import fails with a retryable error.
"""

from __future__ import annotations

import errno
import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from openworld_moments.ingest.library import fsync_directory
from openworld_moments.media.availability import DOWNLOAD_REQUIRED, cloud_only

CHUNK_BYTES = 1024 * 1024
_NO_SPACE = frozenset({errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)})


class ImportCancelled(Exception):
    """Cancellation was requested while reading or copying."""


class FileStepError(Exception):
    """A hashing/copy/promotion step failed. ``code`` is stable; ``message`` has no path."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class Fingerprint:
    """What was read: the stat snapshot taken before reading, and the digest."""

    sha256: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class Staged:
    path: Path
    fingerprint: Fingerprint


def snapshot(path: Path) -> os.stat_result:
    try:
        info = path.stat()
        if cloud_only(info):
            raise FileStepError("media.download_required", DOWNLOAD_REQUIRED, retryable=True)
        return info
    except FileNotFoundError as exc:
        raise FileStepError("media.not_found", "The file disappeared during import.") from exc
    except OSError as exc:
        raise FileStepError(
            "media.unreadable", f"The file cannot be read: {exc.strerror}.", retryable=True
        ) from exc


def _changed() -> FileStepError:
    return FileStepError(
        "import.source_changed",
        "The file changed while it was being read; it may still be copying or syncing.",
        retryable=True,
    )


def _check_stable(path: Path, before: os.stat_result, read: int) -> None:
    after = snapshot(path)
    if (
        read != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise _changed()


def _read_error(exc: OSError) -> FileStepError:
    if isinstance(exc, PermissionError):
        return FileStepError("media.permission_denied", "The file cannot be read.")
    return FileStepError(
        "media.unreadable", f"The file cannot be read: {exc.strerror}.", retryable=True
    )


def _write_error(exc: OSError) -> FileStepError:
    if exc.errno in _NO_SPACE:
        return FileStepError(
            "import.disk_full", "Not enough free space in the library.", retryable=True
        )
    return FileStepError(
        "import.write_failed",
        f"The library copy could not be written: {exc.strerror}.",
        retryable=True,
    )


OnBytes = Callable[[int], None]


def hash_file(
    path: Path,
    *,
    cancel: threading.Event,
    expected: os.stat_result,
    on_bytes: OnBytes | None = None,
) -> Fingerprint:
    """SHA-256 of a source, read-only, verifying it did not change since ``expected``.

    ``on_bytes(total_read)`` is called after every chunk, for progress on large files.
    """
    digest = hashlib.sha256()
    read = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_BYTES):
                if cancel.is_set():
                    raise ImportCancelled
                digest.update(chunk)
                read += len(chunk)
                if on_bytes is not None:
                    on_bytes(read)
    except OSError as exc:
        raise _read_error(exc) from exc
    _check_stable(path, expected, read)
    return Fingerprint(digest.hexdigest(), read, expected.st_mtime_ns)


def write_chunk(handle: BinaryIO, chunk: bytes) -> None:
    """One write to a staging file. A seam for tests that simulate a full disk."""
    handle.write(chunk)


def stage_copy(
    path: Path,
    staging: Path,
    *,
    cancel: threading.Event,
    expected: os.stat_result,
    on_bytes: OnBytes | None = None,
) -> Staged:
    """Copy a source into ``staging`` while hashing it, then flush it to disk.

    On any failure or cancellation the staging file is removed before the error
    propagates. A hard crash may leave it behind; staging is swept on start.
    """
    try:
        staging.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="import-", suffix=".part", dir=staging)
    except OSError as exc:
        raise _write_error(exc) from exc
    tmp = Path(name)
    digest = hashlib.sha256()
    read = 0
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                source = path.open("rb")
            except OSError as exc:
                raise _read_error(exc) from exc
            with source:
                while True:
                    try:
                        chunk = source.read(CHUNK_BYTES)
                    except OSError as exc:
                        raise _read_error(exc) from exc
                    if not chunk:
                        break
                    if cancel.is_set():
                        raise ImportCancelled
                    digest.update(chunk)
                    try:
                        write_chunk(out, chunk)
                    except OSError as exc:
                        raise _write_error(exc) from exc
                    read += len(chunk)
                    if on_bytes is not None:
                        on_bytes(read)
            try:
                out.flush()
                os.fsync(out.fileno())
            except OSError as exc:
                raise _write_error(exc) from exc
        _check_stable(path, expected, read)
        if tmp.stat().st_size != read:  # verify the byte count that reached the disk
            raise FileStepError(
                "import.write_failed", "The library copy is incomplete.", retryable=True
            )
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return Staged(tmp, Fingerprint(digest.hexdigest(), read, expected.st_mtime_ns))


def promote(staged: Staged, target: Path) -> bool:
    """Move a verified staging file to its content-addressed place.

    Returns False when an intact copy is already there (same size; the name is
    the content hash), in which case the staging file is discarded. Rename on
    the same volume is atomic: readers see no file or the complete file.
    """
    size = staged.fingerprint.size
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if target.stat().st_size == size:
                staged.path.unlink(missing_ok=True)
                return False
        except FileNotFoundError:
            pass
        os.replace(staged.path, target)
        fsync_directory(target.parent)
    except OSError as exc:
        staged.path.unlink(missing_ok=True)
        raise _write_error(exc) from exc
    return True
