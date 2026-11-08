# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caption playback spot check (M27): FFmpeg reads exported SRT/WebVTT with the
same cue count and timings as the project timeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import ToolInfo
from openworld_moments.storage import Database
from tests.exports.conftest import DOCUMENT, build


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_ffmpeg_reads_exported_captions_at_project_times(
    ffprobe: ToolInfo, tmp_path: Path, fmt: str
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    fixture = build(Database.open(tmp_path / "library" / "database.sqlite3"), media)
    path = tmp_path / f"captions.{fmt}"
    path.write_text(fixture.export(fmt)["content"], "utf-8")
    result = run_tool(
        [*ffprobe.command, "-v", "error", "-show_packets", "-of", "json", str(path)],
        timeout_s=30,
    )
    assert result.returncode == 0, result.stderr_tail
    packets = json.loads(result.stdout)["packets"]
    cues = DOCUMENT["project"]["captions"]
    assert len(packets) == len(cues)
    for packet, cue in zip(packets, cues, strict=True):
        start = round(float(packet["pts_time"]) * 1000)
        end = start + round(float(packet["duration_time"]) * 1000)
        assert (start, end) == (cue["start_ms"], cue["end_ms"])
