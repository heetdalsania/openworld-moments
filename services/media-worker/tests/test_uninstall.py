# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from openworld_moments import uninstall


def library_fixture(tmp_path: Path, monkeypatch: Any) -> Path:
    monkeypatch.setattr(uninstall, "roaming_appdata", lambda: tmp_path)
    library = tmp_path / uninstall.APP_ID / "library"
    library.mkdir(parents=True)
    with contextlib.closing(sqlite3.connect(library / "database.sqlite3")) as db, db:
        db.execute("CREATE TABLE marker (id INTEGER)")
    return library


def test_explicit_purge_keeps_external_originals_and_preferences(
    tmp_path: Path, monkeypatch: Any
) -> None:
    library = library_fixture(tmp_path, monkeypatch)
    preferences = library.parent / "preferences.json"
    preferences.write_text("retained")
    outside = tmp_path / "originals"
    outside.mkdir()
    footage = outside / "original.mp4"
    footage.write_bytes(b"immutable original")
    os.link(footage, library / "hardlink.mp4")
    if os.name == "nt":
        command = shutil.which("cmd.exe")
        assert command
        subprocess.run(  # noqa: S603 - fixed command and disposable test paths
            [command, "/c", "mklink", "/J", str(library / "linked"), str(outside)], check=True
        )
    else:
        (library / "linked").symlink_to(outside, target_is_directory=True)
    uninstall.purge_library()
    assert not library.exists()
    assert footage.read_bytes() == b"immutable original"
    assert preferences.read_text() == "retained"
    uninstall.purge_library()  # Missing library is already removed.


def test_purge_refuses_unrecognized_library(tmp_path: Path, monkeypatch: Any) -> None:
    library = library_fixture(tmp_path, monkeypatch)
    (library / "database.sqlite3").write_bytes(b"not a library")
    with pytest.raises(OSError, match="recognizable"):
        uninstall.purge_library()
    assert library.exists()


def test_purge_refuses_linked_root(tmp_path: Path, monkeypatch: Any) -> None:
    library = library_fixture(tmp_path, monkeypatch)
    saved = tmp_path / "external-library"
    library.rename(saved)
    if os.name == "nt":
        command = shutil.which("cmd.exe")
        assert command
        subprocess.run(  # noqa: S603 - fixed command and disposable test paths
            [command, "/c", "mklink", "/J", str(library), str(saved)], check=True
        )
    else:
        library.symlink_to(saved, target_is_directory=True)
    with pytest.raises(OSError, match="Linked"):
        uninstall.purge_library()
    assert (saved / "database.sqlite3").exists()
