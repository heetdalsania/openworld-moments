# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared media test fixtures.

Synthetic clips are generated once per session with the real FFmpeg. Without
FFmpeg these tests skip locally, but fail when ``OWM_REQUIRE_FFMPEG=1`` (CI).
"""

from __future__ import annotations

import os
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from openworld_moments.media.fixtures import generate
from openworld_moments.media.tools import MediaTools, ToolInfo

REQUIRE_FFMPEG = os.environ.get("OWM_REQUIRE_FFMPEG") == "1"


def _need(tool: ToolInfo) -> ToolInfo:
    if tool.ok:
        return tool
    message = f"{tool.name} unavailable: {tool.problem}"
    if REQUIRE_FFMPEG:
        pytest.fail(message + " (OWM_REQUIRE_FFMPEG=1)")
    pytest.skip(message)


@pytest.fixture(scope="session")
def tools() -> MediaTools:
    return MediaTools()


@pytest.fixture(scope="session")
def ffprobe(tools: MediaTools) -> ToolInfo:
    return _need(tools.tool("ffprobe"))


@pytest.fixture(scope="session")
def ffmpeg(tools: MediaTools) -> ToolInfo:
    return _need(tools.tool("ffmpeg"))


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory, ffmpeg: ToolInfo) -> Path:
    out = tmp_path_factory.mktemp("media-fixtures")
    generate(out, ffmpeg)
    return out


@pytest.fixture
def fake_tool(tmp_path: Path) -> Callable[[str, str], ToolInfo]:
    """A stand-in tool: a Python script run by this interpreter (works on every OS)."""

    def make(name: str, body: str) -> ToolInfo:
        script = tmp_path / f"fake_{name}_{abs(hash(body))}.py"
        script.write_text(textwrap.dedent(body), "utf-8")
        return ToolInfo("ffprobe", (sys.executable, str(script)), "test", "ok", "6.1.1")

    return make
