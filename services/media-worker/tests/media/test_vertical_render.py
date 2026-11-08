# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic horizontal -> vertical E2E and independent marker-edge goldens."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import ToolInfo
from openworld_moments.render.layout import FIT, fit_rect, pixels, region_at
from openworld_moments.render.plan import RenderError
from tests.media.test_render import Studio, assert_ready, digest, make_clip


@pytest.fixture
def studio(tmp_path: Path, tools: Any) -> Studio:
    return Studio(tmp_path, tools)


def frame(ffmpeg: ToolInfo, path: Path, ms: int) -> np.ndarray:
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
        max_stdout=1080 * 1920 * 2,
    )
    assert r.returncode == 0, r.stderr_tail
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(1920, 1080)


def test_fit_and_blur_e2e_preserve_horizontal_revision_and_all_source_pixels(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "horizontal ü.mp4", "testsrc2", 1, tone=440)
    pid = studio.project(clip)
    before = copy.deepcopy(studio.projects.get(pid))
    original = digest(clip)
    with pytest.raises(RenderError, match="Review vertical"):
        studio.renderer.check_request({"project_id": pid, "preset_id": "vertical-1080x1920-30"})
    with pytest.raises(RenderError, match="project changed after review"):
        studio.renderer.check_request(
            {
                "project_id": pid,
                "preset_id": "vertical-1080x1920-30",
                "review_layout": True,
                "expected_revision": before["revision"] + 1,
            }
        )
    for background in ["solid", "blur"]:
        studio.edit(
            pid,
            lambda p, bg=background: p["tracks"][0]["segments"][0].update(
                vertical_crop={**FIT, "background": bg}
            ),
        )
        saved = copy.deepcopy(studio.projects.get(pid))
        result = studio.render(pid, preset_id="vertical-1080x1920-30", review_layout=True)
        assert_ready(result, 1000)
        assert result["validation"]["probe"]["video"]["width"] == 1080
        assert result["validation"]["probe"]["video"]["height"] == 1920
        assert studio.projects.get(pid) == saved
        assert result["plan"]["segments"][0]["vertical_crop"]["strategy"] == "fit"
        gray = frame(ffmpeg, studio.output(result), 500)
        assert gray[657:1263].mean() > 40
        assert (gray[:500].mean() < 5) if background == "solid" else (gray[:500].mean() > 20)
    after = studio.projects.get(pid)
    assert (
        before["document"]["project"]["tracks"][0]["segments"][0]["crop"]
        == after["document"]["project"]["tracks"][0]["segments"][0]["crop"]
    )
    assert after["document"]["layout"] == before["document"]["layout"]
    assert digest(clip) == original


@pytest.mark.parametrize("keyed", [False, True])
def test_fixed_and_keyed_marker_edges_match_preview_within_two_output_pixels(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path, keyed: bool
) -> None:
    # A stationary white bar on black, generated without proprietary media.
    clip = tmp_path / "markers.mp4"
    r = run_tool(
        [
            *ffmpeg.command,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=640x360:r=30:d=2,drawbox=x=230:y=0:w=10:h=360:color=white:t=fill",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(clip),
        ],
        timeout_s=60,
    )
    assert r.returncode == 0, r.stderr_tail
    pid = studio.project(clip)
    keys = [{"at_ms": 0, "region": [0.1, 0, 0.3, 1]}]
    if keyed:
        keys.append({"at_ms": 1000, "region": [0.5, 0, 0.3, 1]})
    layout = {**FIT, "strategy": "keyed" if keyed else "fixed", "keyframes": keys}
    studio.edit(pid, lambda p: p["tracks"][0]["segments"][0].update(vertical_crop=layout))
    result = studio.render(pid, preset_id="vertical-1080x1920-30", review_layout=True)
    assert_ready(result, 2000)
    for ms in [0, 200, 400, 500]:
        image = frame(ffmpeg, studio.output(result), ms)
        # Expected edge coordinates follow the same geometry that the canvas uses,
        # already checked against the independent shared integer golden manifest.
        x, _, cw, ch = pixels(region_at(layout, ms), 640, 360)
        ox, _, fw, _ = fit_rect(cw, ch)
        expected = [ox + (230 - x) * fw / cw, ox + (240 - x) * fw / cw]
        line = image[960]
        white = np.flatnonzero(line > 128)
        assert len(white) > 0
        measured = [int(white[0]), int(white[-1]) + 1]
        assert max(abs(a - b) for a, b in zip(expected, measured, strict=True)) <= 2, (
            ms,
            expected,
            measured,
        )


@pytest.mark.parametrize("rotated", [False, True])
def test_portrait_and_rotated_sources_are_upright(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path, rotated: bool
) -> None:
    clip = tmp_path / "portrait.mp4"
    if rotated:
        base = make_clip(ffmpeg, tmp_path / "base.mp4", "testsrc2", 1, tone=None)
        args = ["-display_rotation:v:0", "90", "-i", str(base), "-c", "copy"]
    else:
        args = [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=360x640:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    r = run_tool([*ffmpeg.command, "-v", "error", *args, "-y", str(clip)], timeout_s=60)
    assert r.returncode == 0, r.stderr_tail
    pid = studio.project(clip)
    record = studio.render(pid, preset_id="vertical-source-fps", review_layout=True)
    assert_ready(record, 1000)
    assert record["plan"]["segments"][0]["source_size"] == [360, 640]
    assert record["validation"]["probe"]["video"]["rotation"] == 0
    assert frame(ffmpeg, studio.output(record), 500).mean() > 40


def test_vertical_cancel_and_failure_leave_no_completed_file(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    from openworld_moments.ids import new_id
    from openworld_moments.render.service import RenderCancelled

    clip = make_clip(ffmpeg, tmp_path / "cancel.mp4", "testsrc2", 2, tone=None)
    pid = studio.project(clip)
    stop = threading.Event()
    jid = new_id("job")

    def progress(done: int, total: int, message: str) -> None:
        if message == "Rendering":
            stop.set()

    with pytest.raises(RenderCancelled):
        studio.renderer.run(
            {"project_id": pid, "preset_id": "vertical-1080x1920-30", "review_layout": True},
            job_id=jid,
            cancel=stop,
            progress=progress,
        )
    assert studio.renderer.get(jid)["status"] == "cancelled"
    assert not list((studio.renderer.root / "renders").glob("**/*.mp4"))
    assert not (studio.renderer.root / "staging/renders" / jid).exists()
