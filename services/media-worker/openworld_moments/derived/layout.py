# SPDX-License-Identifier: AGPL-3.0-or-later
"""On-disk layout of derived media (spec 9.6, M08).

::

    library/derived/<asset-id>/proxy-<key16>.mp4
    library/derived/<asset-id>/filmstrip-<key16>/0001.jpg ...
    library/derived/<asset-id>/waveform-<key16>.bin
    library/staging/derived/<job-id>/...        (work in progress only)

* Artifacts are built in staging and moved into place with one rename on the
  same volume, so ``derived/`` never holds a partial artifact.
* Names carry 16 hex digits of the artifact's cache key: a regenerated
  artifact gets a new name, so a player never reads a file while it is being
  replaced, and the old one is removed after the database points at the new one.
* Everything under ``derived/`` is replaceable. Paths stored in the database are
  checked before use, and cleanup never follows a link or leaves ``derived/``.
"""

from __future__ import annotations

import contextlib
import os
import re
import stat
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DERIVED_DIR = "derived"
STAGING_DIR = "staging"
DERIVED_STAGING = "derived"
KEY_CHARS = 16
_ASSET_DIR = re.compile(r"^ast_[0-9A-HJKMNP-TV-Z]{26}$")
_ARTIFACT = re.compile(r"^(proxy|filmstrip|waveform)-[0-9a-f]{16}(\.mp4|\.bin)?$")
NAMES = {
    "proxy": "proxy-{key}.mp4",
    "filmstrip": "filmstrip-{key}",
    "waveform": "waveform-{key}.bin",
}


@dataclass
class CleanupReport:
    removed_files: int = 0
    removed_dirs: int = 0
    freed_bytes: int = 0
    skipped_links: int = 0

    def doc(self) -> dict[str, int]:
        return {
            "removed_files": self.removed_files,
            "removed_dirs": self.removed_dirs,
            "freed_bytes": self.freed_bytes,
            "skipped_links": self.skipped_links,
        }


@dataclass(frozen=True)
class DerivedPaths:
    root: Path  # the library folder
    cache_root: Path | None = None

    @property
    def derived(self) -> Path:
        return (self.cache_root or self.root) / DERIVED_DIR

    @property
    def staging(self) -> Path:
        return (self.cache_root or self.root) / STAGING_DIR / DERIVED_STAGING

    def job_staging(self, job_id: str) -> Path:
        return self.staging / job_id

    @staticmethod
    def relpath(asset_id: str, kind: str, cache_key: str) -> str:
        """``derived/<asset>/<name>``: '/'-separated and relative to the library."""
        if not _ASSET_DIR.match(asset_id):
            raise ValueError("invalid asset id")
        name = NAMES[kind].format(key=cache_key[:KEY_CHARS])
        return str(PurePosixPath(DERIVED_DIR, asset_id, name))

    def resolve(self, relpath: str) -> Path | None:
        """The absolute path of a stored artifact path, or None when it is not exactly
        ``derived/<asset-id>/<artifact-name>`` (the database is not trusted)."""
        candidate = PurePosixPath(relpath)
        parts = candidate.parts
        if candidate.is_absolute() or len(parts) != 3 or parts[0] != DERIVED_DIR:
            return None
        if not _ASSET_DIR.match(parts[1]) or not _ARTIFACT.match(parts[2]):
            return None
        return (self.cache_root or self.root).joinpath(*parts)

    def clean_staging(self, job_id: str | None = None) -> None:
        """Remove one job's staging folder, or all (only when no job is running)."""
        target = self.job_staging(job_id) if job_id else self.staging
        remove_tree(target, CleanupReport(), inside=(self.cache_root or self.root) / STAGING_DIR)

    def remove_artifact(self, relpath: str) -> int:
        """Delete one artifact by its stored path; returns bytes freed."""
        path = self.resolve(relpath)
        if path is None:
            return 0
        report = CleanupReport()
        remove_entry(path, report, inside=self.derived)
        return report.freed_bytes

    def cleanup(self, keep: Iterable[str], asset_ids: Iterable[str]) -> CleanupReport:
        """Remove everything under ``derived/`` that is not a kept artifact.

        ``keep`` are the stored relpaths of current artifacts; ``asset_ids`` the
        assets that still exist (their folders stay even when empty of artifacts).
        Links are never followed: a link found inside ``derived/`` is removed as a
        link, never what it points to.
        """
        report = CleanupReport()
        keep_paths = {p for p in (self.resolve(r) for r in keep) if p is not None}
        assets = set(asset_ids)
        root = self.derived
        if _is_link(root) or not root.is_dir():
            return report
        for entry in _scan(root):
            path = Path(entry.path)
            if entry.is_symlink() or _is_junction(path):
                remove_entry(path, report, inside=root)
                continue
            if not entry.is_dir(follow_symlinks=False) or entry.name not in assets:
                remove_entry(path, report, inside=root)
                continue
            for child in _scan(path):
                child_path = Path(child.path)
                if child_path not in keep_paths or child.is_symlink() or _is_junction(child_path):
                    remove_entry(child_path, report, inside=root)
        return report


def _scan(path: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(path) as entries:
            return sorted(entries, key=lambda e: e.name)
    except OSError:
        return []


def _is_link(path: Path) -> bool:
    return path.is_symlink() or _is_junction(path)


def _is_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)  # Python 3.12+
    return bool(is_junction and is_junction(path))


def _inside(path: Path, root: Path) -> bool:
    """Lexically inside ``root`` (no resolution: links are never followed)."""
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
    except ValueError:
        return False
    return Path(os.path.abspath(path)) != Path(os.path.abspath(root))


def remove_entry(path: Path, report: CleanupReport, *, inside: Path) -> None:
    """Remove a file, link, or folder at ``path`` without following links, and only
    when ``path`` is inside ``inside``."""
    if not _inside(path, inside):
        return
    try:
        info = path.lstat()
    except OSError:
        return
    if stat.S_ISLNK(info.st_mode) or _is_junction(path):
        report.skipped_links += 1
        with contextlib.suppress(OSError):
            # A junction is removed with rmdir (it is a directory entry), a symlink
            # with unlink; neither touches the target.
            if _is_junction(path):
                path.rmdir()
            else:
                path.unlink()
        return
    if stat.S_ISDIR(info.st_mode):
        remove_tree(path, report, inside=inside)
        return
    with contextlib.suppress(OSError):
        path.unlink()
        report.removed_files += 1
        report.freed_bytes += info.st_size


def remove_tree(path: Path, report: CleanupReport, *, inside: Path) -> None:
    if not _inside(path, inside) or _is_link(path) or not path.is_dir():
        return
    for entry in _scan(path):
        remove_entry(Path(entry.path), report, inside=inside)
    with contextlib.suppress(OSError):
        path.rmdir()
        report.removed_dirs += 1


def fsync_file(path: Path) -> None:
    """Flush one of the worker's own staging files to disk. Never used on sources.

    Windows can only flush a handle opened for writing (FlushFileBuffers), so the
    file is opened read-write there; nothing is written.
    """
    flags = os.O_RDWR if sys.platform == "win32" else os.O_RDONLY
    fd = os.open(path, flags | getattr(os, "O_BINARY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_dir(source: Path, target: Path, trash: Path, *, inside: Path) -> None:
    """Move a finished folder into place. An existing target (a forced regeneration
    with the same key) is moved aside first and removed afterwards."""
    if target.exists():
        os.replace(target, trash)
    os.replace(source, target)
    remove_tree(trash, CleanupReport(), inside=inside)
