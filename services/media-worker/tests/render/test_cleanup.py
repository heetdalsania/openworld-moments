# SPDX-License-Identifier: AGPL-3.0-or-later
"""Staging removal retries while Windows still holds a handle after FFmpeg exits."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.render.service import remove_tree


def staging(tmp_path: Path) -> Path:
    folder = tmp_path / "staging" / "job"
    folder.mkdir(parents=True)
    (folder / "render.mp4").write_bytes(b"partial")
    return folder


def test_retries_until_a_locked_file_is_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = staging(tmp_path)
    real = shutil.rmtree
    calls: list[Path] = []

    def locked_twice(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        if len(calls) <= 2:
            raise PermissionError(32, "The process cannot access the file")
        real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", locked_twice)
    assert remove_tree(folder, retry_s=5)
    assert not folder.exists() and len(calls) == 3


def test_gives_up_after_the_deadline_and_reports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = staging(tmp_path)

    def always_locked(path: Any, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(shutil, "rmtree", always_locked)
    assert remove_tree(folder, retry_s=0) is False
    assert folder.exists()


def test_missing_and_unlocked_folders(tmp_path: Path) -> None:
    assert remove_tree(tmp_path / "never-created")
    folder = staging(tmp_path)
    assert remove_tree(folder) and not folder.exists()
