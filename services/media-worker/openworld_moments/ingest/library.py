# SPDX-License-Identifier: AGPL-3.0-or-later
"""On-disk library layout for imports (spec 9.6).

``managed-media/ab/cd/<sha256>.<ext>`` holds complete, validated managed copies
only. Copies are written under ``staging/imports/<job-id>/`` first and moved
into place with an atomic rename on the same volume, so a crash can leave
behind staging files but never a partial file in managed storage.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MANAGED_DIR = "managed-media"
STAGING_DIR = "staging"
IMPORT_STAGING = "imports"


@dataclass(frozen=True)
class LibraryPaths:
    root: Path

    @classmethod
    def for_database(cls, database_path: Path) -> LibraryPaths:
        return cls(Path(database_path).parent)

    @property
    def managed(self) -> Path:
        return self.root / MANAGED_DIR

    @property
    def import_staging(self) -> Path:
        return self.root / STAGING_DIR / IMPORT_STAGING

    def job_staging(self, job_id: str) -> Path:
        return self.import_staging / job_id

    @staticmethod
    def managed_relpath(sha256: str, extension: str) -> str:
        """``managed-media/ab/cd/<sha256><ext>``: '/'-separated and relative to the library,
        so the library folder can be moved as a whole."""
        return str(PurePosixPath(MANAGED_DIR, sha256[:2], sha256[2:4], f"{sha256}{extension}"))

    def resolve_managed(self, relpath: str) -> Path | None:
        """The absolute path of a stored ``managed_path``, or None if it would leave
        managed storage (the database is not trusted to stay well-formed)."""
        candidate = PurePosixPath(relpath)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
            return None
        if candidate.parts[0] != MANAGED_DIR:
            return None
        return self.root.joinpath(*candidate.parts)

    def clean_import_staging(self, job_id: str | None = None) -> None:
        """Remove leftover staging files: one job's, or all (only at worker start, when
        no import is running)."""
        target = self.job_staging(job_id) if job_id else self.import_staging
        shutil.rmtree(target, ignore_errors=True)


def fsync_directory(path: Path) -> None:
    """Persist a rename on POSIX. Windows has no directory handles for this; NTFS
    journals the rename itself."""
    if sys.platform == "win32":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
