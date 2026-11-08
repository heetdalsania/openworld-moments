# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent reader for the desktop SRT golden file; no generated media."""

import subprocess
from pathlib import Path

from openworld_moments.media.tools import ToolInfo


def test_srt_golden_keeps_unicode_and_raw_ampersand_in_ffmpeg(ffmpeg: ToolInfo) -> None:
    assert ffmpeg.path
    golden = Path(__file__).parents[4] / "apps/desktop/src/testing/captions.srt"
    result = subprocess.run(  # noqa: S603 - fixed FFmpeg and repository-owned text fixture
        [ffmpeg.path, "-hide_banner", "-loglevel", "error", "-i", str(golden), "-f", "ass", "-"],
        capture_output=True,
        check=True,
        timeout=15,
    )
    text = result.stdout.decode("utf-8")
    assert "Café & " in text
    assert "&amp;" not in text
    assert "你好, world" in text
    assert "🚗" in text
