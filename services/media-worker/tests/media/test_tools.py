# SPDX-License-Identifier: AGPL-3.0-or-later
"""FFprobe/FFmpeg discovery, version gating, and the capability report."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from openworld_moments import doctor
from openworld_moments.media.tools import (
    MIN_LIBRARIES,
    MediaTools,
    ToolInfo,
    check_command,
    check_libraries,
    inspect_tool,
    parse_version_output,
)

VERSION_9 = """ffprobe version 9.0.1 Copyright (c) 2007-2026 the FFmpeg developers
built with Apple clang version 21.0.0
libavutil      60. 10.100 / 60. 10.100
libavcodec     63.  3.100 / 63.  3.100
libavformat    63.  2.100 / 63.  2.100
"""


@pytest.mark.parametrize(
    ("first_line", "version"),
    [
        ("ffprobe version 9.0.1 Copyright", "9.0.1"),
        ("ffprobe version n7.1 Copyright", "7.1"),
        ("ffprobe version N-118000-g1a2b3c4d5e Copyright", "N-118000-g1a2b3c4d5e"),
        ("ffmpeg version 6.1.1-3ubuntu5 Copyright", "6.1.1-3ubuntu5"),
        ("ffmpeg version 7.1-full_build-www.gyan.dev Copyright", "7.1-full_build-www.gyan.dev"),
    ],
)
def test_version_strings(first_line: str, version: str) -> None:
    parsed, _ = parse_version_output(first_line + "\nlibavformat    61.  7.100 / 61.  7.100\n")
    assert parsed == version


def test_library_versions_are_parsed_and_checked() -> None:
    _, libraries = parse_version_output(VERSION_9)
    assert libraries["libavformat"] == "63.2.100"
    assert libraries["libavcodec"] == "63.3.100"
    assert check_libraries(libraries) is None
    assert MIN_LIBRARIES["libavformat"] == 60


@pytest.mark.parametrize(
    ("libraries", "fragment"),
    [
        ({"libavformat": "59.27.100", "libavcodec": "59.37.100"}, "older than 60"),
        ({"libavcodec": "61.3.100"}, "libavformat version not reported"),
    ],
)
def test_old_or_incomplete_builds_are_rejected(libraries: dict[str, str], fragment: str) -> None:
    problem = check_libraries(libraries)
    assert problem is not None and fragment in problem


def _fake(tmp_path: Path, output: str, code: int = 0) -> tuple[str, ...]:
    script = tmp_path / "fake_tool.py"
    script.write_text(f"import sys\nprint({output!r})\nsys.exit({code})\n", "utf-8")
    return (sys.executable, str(script))


def test_too_old_tool(tmp_path: Path) -> None:
    old = "ffprobe version 5.1.4\nlibavcodec     59. 37.100\nlibavformat    59. 27.100\n"
    info = check_command("ffprobe", _fake(tmp_path, old), "test")
    assert info.status == "too_old" and not info.ok
    assert "FFmpeg 6.0" in (info.problem or "")


def test_tool_that_fails_is_unusable(tmp_path: Path) -> None:
    info = check_command("ffprobe", _fake(tmp_path, "boom", code=1), "test")
    assert info.status == "unusable"


def test_explicit_missing_path(tmp_path: Path) -> None:
    info = inspect_tool("ffprobe", str(tmp_path / "ffprobe"))
    assert info.status == "missing" and info.source == "flag"


def test_env_var_wins_over_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWM_FFPROBE", str(tmp_path / "nowhere" / "ffprobe"))
    info = inspect_tool("ffprobe")
    assert info.source == "env" and info.status == "missing"


def test_not_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OWM_FFPROBE", raising=False)
    monkeypatch.setenv("PATH", "")
    info = inspect_tool("ffprobe")
    assert info.status == "missing" and info.source == "path"
    assert "not found" in (info.problem or "")


def test_unhealthy_tools_are_rechecked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_inspect(name: str, explicit: str | None = None) -> ToolInfo:
        calls.append(name)
        return ToolInfo(name, (), "path", "missing", problem="not found")  # type: ignore[arg-type]

    monkeypatch.setattr("openworld_moments.media.tools.inspect_tool", fake_inspect)
    tools = MediaTools()
    tools.tool("ffprobe")
    tools.tool("ffprobe")
    assert calls == ["ffprobe", "ffprobe"], (
        "a missing tool is looked up again (user may install it)"
    )


def test_capability_report_with_real_tools(ffprobe: ToolInfo, ffmpeg: ToolInfo) -> None:
    report = MediaTools().capabilities()
    assert report["probe_ready"] is True
    assert report["ffprobe"]["status"] == "ok"
    assert report["ffprobe"]["version"] == ffprobe.version
    assert set(report["decoders"]) == {"h264", "hevc", "av1", "vp9", "aac", "opus"}
    assert report["decoders"]["h264"] is True
    assert report["encoders"]["libx264"] is True
    assert report["minimum"] == {"ffmpeg_release": "6.0", "libavformat": 60, "libavcodec": 60}


def test_capability_report_without_tools(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing")
    report = MediaTools(ffprobe=missing, ffmpeg=missing).capabilities()
    assert report["probe_ready"] is False
    assert report["ffprobe"]["status"] == "missing"
    assert not any(report["decoders"].values())


def test_doctor_human_and_json(
    ffprobe: ToolInfo, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert doctor.main([]) == 0
    text = capsys.readouterr().out
    assert "Media probing: ready" in text and "ffprobe" in text

    assert doctor.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["probe_ready"] is True

    missing = str(tmp_path / "missing")
    assert doctor.main(["--ffprobe", missing, "--ffmpeg", missing]) == 1
    assert "NOT READY" in capsys.readouterr().out


def test_fake_tool_fixture_is_ok(fake_tool: Callable[[str, str], ToolInfo]) -> None:
    assert fake_tool("x", "print(1)").ok
