# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real FFmpeg moving-blur geometry, strength, endpoints and immutable sources."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import ToolInfo
from openworld_moments.privacy.blur import pixels, region_at
from tests.media.test_render import Studio, assert_ready, digest


@pytest.fixture
def studio(tmp_path: Path, tools: Any) -> Studio:
    return Studio(tmp_path, tools)


def frame(ffmpeg: ToolInfo, path: Path, ms: int, w: int, h: int) -> np.ndarray:
    r = run_tool(
        [
            *ffmpeg.command,
            "-v",
            "error",
            "-ss",
            f"{ms / 1000:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "format=gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        timeout_s=60,
        max_stdout=w * h * 2,
    )
    assert r.returncode == 0, r.stderr_tail
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(h, w)


@pytest.mark.parametrize("vertical", [False, True])
def test_moving_blur_matches_preview_geometry(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path, vertical: bool
) -> None:
    source = tmp_path / "synthetic-checker.mp4"
    r = run_tool(
        [
            *ffmpeg.command,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=size=640x360:rate=30:duration=3,geq=lum='if(mod(floor(X/4)+floor(Y/4),2),220,30)':cb=128:cr=128",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(source),
        ],
        timeout_s=60,
    )
    assert r.returncode == 0, r.stderr_tail
    before = digest(source)
    pid = studio.project(source)
    data = json.loads(
        (
            Path(__file__).resolve().parents[4] / "fixtures/synthetic/privacy-blur-v1.json"
        ).read_text()
    )
    blur = copy.deepcopy(data["blur"])
    # In vertical output place the blur over the actual fit foreground.
    if vertical:
        blur["region"] = [0.1, 0.4, 0.2, 0.1]
        blur["keyframes"] = [
            dict(at_ms=0, region=[0.1, 0.4, 0.2, 0.1]),
            dict(at_ms=1000, region=[0.6, 0.5, 0.2, 0.1]),
        ]
    studio.edit(pid, lambda p: p.update(overlays=[blur]))
    result = studio.render(
        pid,
        preset_id="vertical-1080x1920-30" if vertical else "horizontal-720p30",
        review_layout=vertical,
    )
    assert_ready(result, 3000)
    w, h = (1080, 1920) if vertical else (1280, 720)
    for ms in (600, 1000, 1600, 2300):
        image = frame(ffmpeg, studio.output(result), ms, w, h)
        x, y, bw, bh = pixels(region_at(blur, ms), w, h)
        inside = image[y + bh // 4 : y + 3 * bh // 4, x + bw // 4 : x + 3 * bw // 4]
        assert inside.std() < 12, (ms, inside.std())
        stripe = image[y + bh // 4 : y + 3 * bh // 4, :]
        mask = (stripe.std(axis=0) < 12) & (stripe.mean(axis=0) > 30) & (stripe.mean(axis=0) < 220)
        center = x + bw // 2
        assert mask[center]
        left = right = center
        while left > 0 and mask[left - 1]:
            left -= 1
        while right + 1 < w and mask[right + 1]:
            right += 1
        assert abs(left - x) <= 2, (ms, x, left)
        assert abs(right + 1 - (x + bw)) <= 2, (ms, x + bw, right + 1)
        # The corresponding region left behind remains detailed once the blur moves.
        if ms >= 1600:
            original = image[
                (h * 4 // 10 if vertical else h // 10) + 10 : (h * 4 // 10 if vertical else h // 10)
                + 60,
                w // 10 + 10 : w // 10 + 60,
            ]
            assert original.std() > 25, (ms, original.std())
    # End exclusive: detailed checker returns immediately after the configured range.
    after = frame(ffmpeg, studio.output(result), 2600, w, h)
    x, y, bw, bh = pixels(region_at(blur, 2300), w, h)
    assert after[y + 10 : y + bh - 10, x + 10 : x + bw - 10].std() > 25
    assert result["plan"]["blur_overlays"][0]["keyframes"] == blur["keyframes"]
    assert result["plan"]["privacy_review"]["acknowledged"]
    assert before == digest(source)
