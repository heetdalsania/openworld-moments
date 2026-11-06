# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn the paths of an import request into an ordered list of candidate files.

Rules (M05):

* A path the user named is used as given, even if it is a link: they chose it.
* Inside a selected folder, nothing may lead outside that folder. Linked folders
  (symlinks, Windows junctions) are never followed. A linked file is used only
  when its real target is inside the selected folder, and the target, not the
  link, is what gets opened, so the link cannot be swapped afterwards.
* Only files with a known video extension are candidates; everything else in a
  folder is reported as skipped, never silently dropped.
* A file reached twice in one request (e.g. two overlapping folders) is
  reported once.
* Scans are bounded: at most ``max_items`` reported files and ``max_depth``
  folder levels.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from openworld_moments.media.probe import VIDEO_EXTENSIONS

MAX_ITEMS = 10_000
MAX_DEPTH = 32


@dataclass(frozen=True)
class Candidate:
    """A media file to import."""

    source: int
    path: Path
    relative_path: str | None


@dataclass(frozen=True)
class Problem:
    """A file or folder that will not be imported, and why."""

    source: int
    relative_path: str | None
    outcome: str  # 'skipped' or 'failed'
    code: str
    message: str
    retryable: bool = False


Entry = Candidate | Problem


class ScanTooLarge(Exception):
    """The request names more files than one import may report."""


def is_media_name(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXTENSIONS


def _skip(source: int, rel: str, code: str, message: str) -> Problem:
    return Problem(source, rel, "skipped", code, message)


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or entry.is_junction()


def scan(
    paths: Iterable[str],
    *,
    recursive: bool,
    max_items: int = MAX_ITEMS,
    max_depth: int = MAX_DEPTH,
) -> list[Entry]:
    """Candidates and problems in request order, then name order within folders."""
    scanner = _Scanner(recursive=recursive, max_items=max_items, max_depth=max_depth)
    for source, raw in enumerate(paths):
        scanner.root(source, Path(raw))
    return scanner.entries


class _Scanner:
    def __init__(self, *, recursive: bool, max_items: int, max_depth: int) -> None:
        self.recursive = recursive
        self.max_items = max_items
        self.max_depth = max_depth
        self.entries: list[Entry] = []
        self._seen: set[tuple[int, int]] = set()

    def add(self, entry: Entry) -> None:
        if len(self.entries) >= self.max_items:
            raise ScanTooLarge(f"more than {self.max_items} files")
        self.entries.append(entry)

    def candidate(self, source: int, path: Path, rel: str | None, info: os.stat_result) -> None:
        identity = (info.st_dev, info.st_ino)
        if info.st_ino and identity in self._seen:
            return
        self._seen.add(identity)
        self.add(Candidate(source, path, rel))

    def root(self, source: int, root: Path) -> None:
        try:
            info = root.stat()
        except FileNotFoundError:
            self.add(Problem(source, None, "failed", "media.not_found", "The path does not exist."))
            return
        except PermissionError:
            self.add(
                Problem(
                    source,
                    None,
                    "failed",
                    "media.permission_denied",
                    "The path cannot be read (permission denied).",
                )
            )
            return
        except OSError as exc:
            self.add(
                Problem(
                    source,
                    None,
                    "failed",
                    "media.unreadable",
                    f"The path cannot be read: {exc.strerror}.",
                )
            )
            return
        if stat.S_ISREG(info.st_mode):
            if is_media_name(root.name):
                self.candidate(source, root, None, info)
            else:
                self.add(
                    Problem(
                        source,
                        None,
                        "failed",
                        "import.not_media_extension",
                        "Not a supported video file type.",
                    )
                )
        elif stat.S_ISDIR(info.st_mode):
            self.folder(source, root)
        else:
            self.add(
                Problem(
                    source,
                    None,
                    "failed",
                    "media.not_a_file",
                    "The path is not a regular file or folder.",
                )
            )

    def folder(self, source: int, root: Path) -> None:
        real_root = root.resolve(strict=True)
        stack: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
        while stack:
            folder, parts = stack.pop()
            rel_folder = "/".join(parts) or None
            try:
                with os.scandir(folder) as it:
                    children = sorted(it, key=lambda e: e.name)
            except PermissionError:
                self.add(
                    Problem(
                        source,
                        rel_folder,
                        "failed",
                        "media.permission_denied",
                        "A folder cannot be read (permission denied).",
                    )
                )
                continue
            except OSError as exc:
                self.add(
                    Problem(
                        source,
                        rel_folder,
                        "failed",
                        "media.unreadable",
                        f"A folder cannot be read: {exc.strerror}.",
                    )
                )
                continue
            subfolders: list[tuple[Path, tuple[str, ...]]] = []
            for child in children:
                child_parts = (*parts, child.name)
                rel = "/".join(child_parts)
                try:
                    sub = self.child(source, child, rel, len(child_parts), real_root)
                except OSError as exc:
                    self.add(
                        Problem(
                            source,
                            rel,
                            "failed",
                            "media.unreadable",
                            f"The entry cannot be read: {exc.strerror}.",
                        )
                    )
                    continue
                if sub is not None:
                    subfolders.append((sub, child_parts))
            # Depth-first in name order: push reversed so the first name is scanned first.
            stack.extend(reversed(subfolders))

    def child(
        self, source: int, child: os.DirEntry[str], rel: str, depth: int, real_root: Path
    ) -> Path | None:
        """Handle one folder entry; return it when it is a subfolder to scan."""
        path = Path(child.path)
        if _is_link(child):
            self.linked(source, path, rel, real_root)
        elif child.is_dir(follow_symlinks=False):
            if not self.recursive:
                return None
            if depth > self.max_depth:
                self.add(
                    _skip(
                        source,
                        rel,
                        "import.too_deep",
                        f"Folders nested deeper than {self.max_depth} levels are not scanned.",
                    )
                )
                return None
            # Belt and braces against mount tricks the link checks cannot see.
            if not path.resolve(strict=True).is_relative_to(real_root):
                self.add(
                    _skip(
                        source,
                        rel,
                        "import.outside_root",
                        "The folder leads outside the selected folder.",
                    )
                )
                return None
            return path
        elif child.is_file(follow_symlinks=False):
            if is_media_name(child.name):
                self.candidate(source, path, rel, child.stat(follow_symlinks=False))
            else:
                self.add(
                    _skip(
                        source,
                        rel,
                        "import.not_media_extension",
                        "Not a supported video file type.",
                    )
                )
        else:
            self.add(
                _skip(
                    source, rel, "media.not_a_file", "Not a regular file (device, pipe, or socket)."
                )
            )
        return None

    def linked(self, source: int, path: Path, rel: str, real_root: Path) -> None:
        try:
            target = path.resolve(strict=True)
            info = target.stat()
        except (OSError, RuntimeError):  # RuntimeError: symlink loop
            self.add(
                _skip(source, rel, "import.broken_link", "The link points to nothing readable.")
            )
            return
        if stat.S_ISDIR(info.st_mode):
            self.add(_skip(source, rel, "import.linked_folder", "Linked folders are not followed."))
        elif not target.is_relative_to(real_root):
            self.add(
                _skip(
                    source,
                    rel,
                    "import.outside_root",
                    "The link points outside the selected folder.",
                )
            )
        elif not stat.S_ISREG(info.st_mode):
            self.add(
                _skip(source, rel, "media.not_a_file", "The link does not point to a regular file.")
            )
        elif not (is_media_name(path.name) and is_media_name(target.name)):
            self.add(
                _skip(source, rel, "import.not_media_extension", "Not a supported video file type.")
            )
        else:
            self.candidate(source, target, rel, info)
