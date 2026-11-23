# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native macOS fixture and render matrix for both bundled FFmpeg architectures."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

from openworld_moments.derived.service import DerivedMedia
from openworld_moments.ids import new_id
from openworld_moments.media.macos_capabilities import capability_report
from openworld_moments.media.process import ToolError, run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.render.encoders import VIDEOTOOLBOX
from openworld_moments.render.validate import probe
from tests.media.test_render import Studio, assert_ready, digest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS media matrix")

PRESETS = ("horizontal-1080p30", "vertical-1080x1920-30")
FIXTURES = {
    "h264_aac.mp4": False,
    "no_audio.mp4": False,
    "vfr.mp4": False,
    "rotated.mp4": False,
    "hdr_pq.mp4": True,
    "hevc.mp4": True,
    "hevc_hlg.mp4": True,
}


def make_hlg_fixture(ffmpeg: ToolInfo, target: Path) -> None:
    result = run_tool(
        [
            *ffmpeg.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-vf",
            "format=yuv420p10le,setparams=color_primaries=bt2020:color_trc=arib-std-b67:"
            "colorspace=bt2020nc:range=tv",
            "-c:v",
            "libx265",
            "-tag:v",
            "hvc1",
            "-preset",
            "ultrafast",
            "-x265-params",
            "pools=none:frame-threads=1:log-level=error",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ],
        timeout_s=20,
    )
    assert result.returncode == 0, result.stderr_tail


def test_native_macos_media_matrix(
    tools: MediaTools, ffmpeg: ToolInfo, ffprobe: ToolInfo, media_dir: Path, tmp_path: Path
) -> None:
    if sys.platform == "win32":  # `resource` is POSIX-only; tells mypy on Windows too
        pytest.skip("native macOS media matrix")
    import resource

    hevc = media_dir / "hevc.mp4"
    report_file = os.environ.get("OWM_MACOS_MEDIA_REPORT")
    if not hevc.is_file() and not report_file:
        pytest.skip("Set OWM_FIXTURE_FFMPEG to an FFmpeg with libx265 for the full matrix")
    assert hevc.is_file(), "HEVC fixture required for the macOS media matrix"
    fixture_tool = MediaTools(ffmpeg=os.environ.get("OWM_FIXTURE_FFMPEG")).tool("ffmpeg")
    assert fixture_tool.ok
    hlg = tmp_path / "hevc_hlg.mp4"
    make_hlg_fixture(fixture_tool, hlg)
    report = capability_report(
        Studio(tmp_path / "probe", tools).renderer, media_dir / "h264_aac.mp4", hevc
    )
    hardware = report["h264_yuv420p_encode"]
    for preset_id in ("horizontal-source-fps", "vertical-source-fps"):
        assert not hardware[preset_id]["available"]
    report["matrix"] = {}
    for name, proxy_needed in FIXTURES.items():
        source = hlg if name == hlg.name else media_dir / name
        before = digest(source)
        studio = Studio(tmp_path / source.stem, tools)
        project_id = studio.project(source)
        src = studio.projects.get(project_id)["document"]["sources"][0]
        start = time.monotonic()
        derived = DerivedMedia(studio.database, tools).generate(
            {"asset_id": src["asset_id"]},
            job_id=new_id("job"),
            cancel=threading.Event(),
            progress=lambda *_: None,
        )
        assert derived["outcomes"]["proxy"] == ("generated" if proxy_needed else "not_needed")
        assert derived["outcomes"]["filmstrip"] == "generated"
        assert derived["outcomes"]["waveform"] == (
            "not_applicable"
            if name
            in {
                "no_audio.mp4",
                "vfr.mp4",
            }
            else "generated"
        )
        fixture = {
            "proxy": derived["outcomes"]["proxy"],
            "derived_seconds": round(time.monotonic() - start, 3),
            "renders": [],
        }
        for preset_id in PRESETS:
            encoders = ["libx264"]
            # A runner without an accessible GPU still validates the CPU pipeline.
            if name in {"h264_aac.mp4", "hdr_pq.mp4"} and hardware[preset_id]["available"]:
                encoders.append(VIDEOTOOLBOX.id)
            for encoder in encoders:
                start = time.monotonic()
                record = studio.render(
                    project_id, preset_id=preset_id, encoder=encoder, review_layout=True
                )
                assert_ready(record, record["plan"]["duration_ms"])
                audit = probe(tools, studio.output(record), threading.Event())
                assert audit is not None
                video = next(s for s in audit["streams"] if s["codec_type"] == "video")
                assert (video["width"], video["height"]) == (
                    (1080, 1920) if preset_id.startswith("vertical") else (1920, 1080)
                )
                audio = next((s for s in audit["streams"] if s["codec_type"] == "audio"), None)
                if audio:
                    assert abs(float(audio["duration"]) - float(video["duration"])) <= 0.100
                    assert abs(float(audio["start_time"]) - float(video["start_time"])) <= 0.035
                if name in {"hdr_pq.mp4", hlg.name}:
                    assert [
                        video[k]
                        for k in ("color_primaries", "color_transfer", "color_space", "color_range")
                    ] == ["bt709", "bt709", "bt709", "tv"]
                fixture["renders"].append(
                    {
                        "preset": preset_id,
                        "encoder": encoder,
                        "seconds": round(time.monotonic() - start, 3),
                        "duration_ms": record["output"]["duration_ms"],
                        "bytes": record["output"]["size_bytes"],
                        "checks": record["validation"]["checks"],
                    }
                )
        assert digest(source) == before
        report["matrix"][name] = fixture
    report["peak_child_rss_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    report["thermal_warning"] = None
    try:
        thermal = run_tool(["/usr/bin/pmset", "-g", "therm"], timeout_s=5)
        if thermal.returncode == 0:
            message = thermal.stdout.decode(errors="replace").lower()
            if "thermal warning level" in message:
                report["thermal_warning"] = "no thermal warning level" not in message
    except ToolError:
        pass  # Some CI environments do not expose thermal state.
    if report_file:
        Path(report_file).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("preset_id", PRESETS)
def test_sync_of_picture_and_audio_after_trim(
    preset_id: str, tools: MediaTools, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    source = tmp_path / "sync.mp4"
    result = run_tool(
        [
            *ffmpeg.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=320x180:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=if(gte(t\\,0.75)\\,0.25*sin(2*PI*440*t)\\,0):s=48000:d=2",
            "-vf",
            "drawbox=color=white:t=fill:enable='gte(t,0.75)'",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        timeout_s=20,
    )
    assert result.returncode == 0, result.stderr_tail
    studio = Studio(tmp_path, tools)
    project_id = studio.project(source, start_ms=200, trim_end_ms=200)
    encoders = ["libx264"]
    if next(
        e
        for e in studio.renderer.encoder_status(preset_id=preset_id)["encoders"]
        if e["id"] == VIDEOTOOLBOX.id
    )["available"]:
        encoders.append(VIDEOTOOLBOX.id)
    for encoder in encoders:
        record = studio.render(project_id, preset_id=preset_id, encoder=encoder, review_layout=True)
        signal = run_tool(
            [
                *ffmpeg.command,
                "-hide_banner",
                "-nostdin",
                "-i",
                str(studio.output(record)),
                "-vf",
                "blackdetect=d=0.1",
                "-af",
                "silencedetect=n=-45dB:d=0.1",
                "-f",
                "null",
                "-",
            ],
            timeout_s=20,
        )
        black = re.search(r"black_end:([\d.]+)", signal.stderr_tail)
        silence = re.search(r"silence_end:\s*([\d.]+)", signal.stderr_tail)
        assert signal.returncode == 0 and black and silence, signal.stderr_tail
        picture_at, audio_at = float(black[1]), float(silence[1])
        assert abs(picture_at - 0.55) <= 0.055
        assert abs(audio_at - picture_at) <= 0.055
