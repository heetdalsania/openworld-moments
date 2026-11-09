# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit interactive uninstall only; never accepts a caller-selected deletion path."""

from __future__ import annotations

import ctypes
import shutil
import sys
from pathlib import Path

APP_ID = "org.openworldmoments.desktop"


def roaming_appdata() -> Path:
    if sys.platform != "win32":
        raise OSError("Library removal is available only in the Windows uninstaller.")
    buffer = ctypes.create_unicode_buffer(32768)
    # CSIDL_APPDATA: use the OS folder, not an inherited APPDATA environment override.
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x1A, None, 0, buffer) != 0:
        raise OSError("Cannot locate the Windows application-data folder.")
    return Path(buffer.value)


def purge_library() -> None:
    parent = roaming_appdata() / APP_ID
    library = parent / "library"
    if not library.exists() and not library.is_symlink() and not library.is_junction():
        return
    if any(p.is_symlink() or p.is_junction() for p in (parent, library)):
        raise OSError("Linked library roots must be removed manually.")
    database = library / "database.sqlite3"
    if database.is_symlink() or not database.is_file() or database.stat().st_nlink != 1:
        raise OSError("The folder is not a recognizable application library.")
    with database.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise OSError("The folder is not a recognizable application library.")
    # Python 3.12 rmtree unlinks nested symlinks/junctions without visiting their targets.
    # No process or arbitrary path can request this command through the worker API.
    shutil.rmtree(library)
