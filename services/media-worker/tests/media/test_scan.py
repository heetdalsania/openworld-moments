# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import scanning: folder rules, symlink and traversal containment, and limits (M05)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openworld_moments.ingest.scan import Candidate, Problem, ScanTooLarge, scan


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _symlink(link: Path, target: Path, *, folder: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=folder)
    except OSError:
        pytest.skip("symlinks need extra privileges on this Windows runner")


def _summary(entries: list[Candidate | Problem]) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    for e in entries:
        out.append(
            (e.relative_path, "candidate" if isinstance(e, Candidate) else f"{e.outcome}:{e.code}")
        )
    return out


def test_folder_scan_reports_every_file_in_order(tmp_path: Path) -> None:
    root = tmp_path / "Captures"
    _touch(root / "b.mp4")
    _touch(root / "a.MKV")
    _touch(root / "notes.txt")
    _touch(root / "sub" / "c.mov")
    assert _summary(scan([str(root)], recursive=False)) == [
        ("a.MKV", "candidate"),
        ("b.mp4", "candidate"),
        ("notes.txt", "skipped:import.not_media_extension"),
    ]
    assert _summary(scan([str(root)], recursive=True))[-1] == ("sub/c.mov", "candidate")


def test_named_files_are_used_as_given(tmp_path: Path) -> None:
    clip = _touch(tmp_path / "clip.mp4")
    text = _touch(tmp_path / "readme.txt")
    entries = scan([str(clip), str(text), str(tmp_path / "gone.mp4")], recursive=False)
    assert isinstance(entries[0], Candidate) and entries[0].path == clip
    assert entries[0].relative_path is None
    assert [(e.source, e.outcome, e.code) for e in entries[1:] if isinstance(e, Problem)] == [
        (1, "failed", "import.not_media_extension"),
        (2, "failed", "media.not_found"),
    ]


def test_symlink_out_of_the_root_is_not_followed(tmp_path: Path) -> None:
    outside = _touch(tmp_path / "outside" / "secret.mp4")
    root = tmp_path / "root"
    _touch(root / "ok.mp4")
    _symlink(root / "escape.mp4", outside)
    _symlink(root / "relative-escape.mp4", Path("..") / "outside" / "secret.mp4")
    summary = dict(_summary(scan([str(root)], recursive=True)))
    assert summary["escape.mp4"] == "skipped:import.outside_root"
    assert summary["relative-escape.mp4"] == "skipped:import.outside_root"
    assert summary["ok.mp4"] == "candidate"


def test_linked_folders_are_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _touch(outside / "clip.mp4")
    root = tmp_path / "root"
    root.mkdir()
    _symlink(root / "linked", outside, folder=True)
    _symlink(root / "loop", root, folder=True)
    summary = dict(_summary(scan([str(root)], recursive=True)))
    assert summary == {
        "linked": "skipped:import.linked_folder",
        "loop": "skipped:import.linked_folder",
    }


def test_link_inside_the_root_opens_the_target(tmp_path: Path) -> None:
    root = tmp_path / "root"
    target = _touch(root / "real" / "clip.mp4")
    _symlink(root / "alias.mp4", target)
    entries = scan([str(root)], recursive=True)
    candidates = [e for e in entries if isinstance(e, Candidate)]
    # Reached twice (link + file): reported once, and the real file is what is opened.
    assert len(candidates) == 1
    assert candidates[0].path == target.resolve()


def test_broken_link_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _symlink(root / "dangling.mp4", root / "nothing.mp4")
    assert _summary(scan([str(root)], recursive=True)) == [
        ("dangling.mp4", "skipped:import.broken_link")
    ]


def test_dot_dot_in_a_named_root_cannot_widen_a_scan(tmp_path: Path) -> None:
    # A '..' in the user's own path is resolved once; the scan stays inside what it names.
    _touch(tmp_path / "a" / "inside.mp4")
    _touch(tmp_path / "b" / "other.mp4")
    entries = scan([str(tmp_path / "b" / ".." / "a")], recursive=True)
    assert _summary(entries) == [("inside.mp4", "candidate")]


def test_overlapping_roots_report_a_file_once(tmp_path: Path) -> None:
    clip = _touch(tmp_path / "root" / "clip.mp4")
    entries = scan([str(tmp_path / "root"), str(clip)], recursive=True)
    assert len([e for e in entries if isinstance(e, Candidate)]) == 1


def test_depth_and_size_limits(tmp_path: Path) -> None:
    deep = tmp_path / "root"
    _touch(deep / "1" / "2" / "3" / "clip.mp4")
    summary = _summary(scan([str(deep)], recursive=True, max_depth=2))
    assert summary == [("1/2/3", "skipped:import.too_deep")]
    for i in range(5):
        _touch(tmp_path / "many" / f"{i}.mp4")
    with pytest.raises(ScanTooLarge):
        scan([str(tmp_path / "many")], recursive=False, max_items=4)
