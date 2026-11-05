# SPDX-License-Identifier: AGPL-3.0-or-later
"""Path edge cases and source preservation."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest

from openworld_moments.media.probe import ProbeError, check_path_param, probe_file
from openworld_moments.media.tools import ToolInfo

AWKWARD_NAMES = [
    "clip with spaces.mp4",
    "Capture ✓ 日本語 émoji 🎮.mp4",
    "-leading-dash.mp4",
    "100% done & more.mp4",
    "http---example.com-x.mp4",
    "semi;colon $HOME `tick`.mp4",
]
if sys.platform != "win32":
    # Not valid Windows file names. 'concat:' would be a protocol without file:.
    AWKWARD_NAMES += [
        "concat:a.mp4|b.mp4",
        'quote\'s and "double".mp4',
        "back\\slash.mp4",
    ]


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_awkward_file_names_probe(
    media_dir: Path, ffprobe: ToolInfo, tmp_path: Path, name: str
) -> None:
    folder = tmp_path / "folder with spaces ünïcødé"
    folder.mkdir()
    target = folder / name
    shutil.copyfile(media_dir / "h264_aac.mp4", target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    mtime = target.stat().st_mtime_ns

    probe = probe_file(target, ffprobe)

    assert probe["video"]["codec"] == "h264"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert target.stat().st_mtime_ns == mtime
    assert sorted(p.name for p in folder.iterdir()) == [name], "probe wrote next to the source"


def test_symlink_to_a_file_is_followed(media_dir: Path, ffprobe: ToolInfo, tmp_path: Path) -> None:
    link = tmp_path / "link.mp4"
    try:
        link.symlink_to(media_dir / "h264_aac.mp4")
    except OSError:
        pytest.skip("symlinks need extra privileges on this Windows runner")
    assert probe_file(link, ffprobe)["video"]["codec"] == "h264"


def test_missing_file(ffprobe: ToolInfo, tmp_path: Path) -> None:
    with pytest.raises(ProbeError) as caught:
        probe_file(tmp_path / "nope.mp4", ffprobe)
    assert caught.value.code == "media.not_found"


def test_directory_is_not_a_file(ffprobe: ToolInfo, tmp_path: Path) -> None:
    folder = tmp_path / "looks-like.mp4"
    folder.mkdir()
    with pytest.raises(ProbeError) as caught:
        probe_file(folder, ffprobe)
    assert caught.value.code == "media.not_a_file"


def test_unreadable_file(media_dir: Path, ffprobe: ToolInfo, tmp_path: Path) -> None:
    # A sys.platform check (not skipif) so mypy also skips the POSIX-only calls on Windows.
    if sys.platform == "win32":
        pytest.skip("POSIX permission bits")
    if os.geteuid() == 0:
        pytest.skip("root can read anything")
    target = tmp_path / "locked.mp4"
    shutil.copyfile(media_dir / "h264_aac.mp4", target)
    target.chmod(0)
    try:
        with pytest.raises(ProbeError) as caught:
            probe_file(target, ffprobe)
        assert caught.value.code == "media.permission_denied"
    finally:
        target.chmod(0o600)


@pytest.mark.parametrize(
    "value",
    ["", "relative/clip.mp4", "clip.mp4", 42, None, "/ok/" + "x" * 5000, "/nul\0byte.mp4"],
)
def test_path_param_is_validated(value: object) -> None:
    with pytest.raises(ValueError, match="path"):
        check_path_param(value)


def test_absolute_path_param_is_accepted(tmp_path: Path) -> None:
    assert check_path_param(str(tmp_path / "x.mp4")) == str(tmp_path / "x.mp4")
