# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate a rendered file before it may be marked complete (spec 13.4).

FFprobe confirms container, duration, streams, resolution, pixel format, frame rate,
rotation and metadata. Frames are decoded from the start, middle and end. A sample
that is black although the source at that moment is not is reported as a filter
error. Empty or malformed output fails every check.
"""

from __future__ import annotations

import json
import threading
from fractions import Fraction
from pathlib import Path
from typing import Any

from openworld_moments.media.process import ToolCancelled, ToolError, run_tool
from openworld_moments.media.tools import MediaTools

DURATION_TOLERANCE_MS = 100
BLACK_LUMA = 20.0
SOURCE_LUMA = 40.0
SAMPLE_SIZE = (64, 36)
ALLOWED_TAGS = {"major_brand", "minor_version", "compatible_brands", "encoder"}


def _mean_luma(tool: Any, path: Path, at_ms: int, cancel: threading.Event) -> float | None:
    try:
        result = run_tool(
            [
                *tool.command,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file,pipe",
                "-ss",
                f"{max(0, at_ms) / 1000:.3f}",
                "-i",
                f"file:{path}",
                "-frames:v",
                "1",
                "-vf",
                f"scale={SAMPLE_SIZE[0]}:{SAMPLE_SIZE[1]}:flags=area,format=gray",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            timeout_s=60,
            cancel=cancel,
            max_stdout=SAMPLE_SIZE[0] * SAMPLE_SIZE[1] * 2,
        )
    except ToolCancelled:
        raise
    except ToolError:
        return None
    if result.returncode or len(result.stdout) != SAMPLE_SIZE[0] * SAMPLE_SIZE[1]:
        return None
    return sum(result.stdout) / len(result.stdout)


def probe(tools: MediaTools, path: Path, cancel: threading.Event) -> dict[str, Any] | None:
    tool = tools.tool("ffprobe")
    try:
        result = run_tool(
            [
                *tool.command,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                f"file:{path}",
            ],
            timeout_s=60,
            cancel=cancel,
            max_stdout=4 * 1024 * 1024,
        )
        if result.returncode:
            return None
        doc = json.loads(result.stdout.decode("utf-8"))
        return doc if isinstance(doc, dict) and "format" in doc else None
    except ToolCancelled:
        raise
    except (ToolError, ValueError):
        return None


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            return int(float(side["rotation"]))
    rotate = (stream.get("tags") or {}).get("rotate")
    return int(rotate) if rotate is not None else 0


def _fps(value: str | None) -> Fraction | None:
    try:
        fraction = Fraction(value or "")
    except (ValueError, ZeroDivisionError):
        return None
    return fraction if fraction > 0 else None


def source_at(plan: dict[str, Any], timeline_ms: int) -> tuple[int, int]:
    """(source index, source ms) shown at ``timeline_ms`` of the output."""
    for piece in plan["segments"]:
        length = piece["out_ms"] - piece["in_ms"]
        if timeline_ms < piece["timeline_start_ms"] + length:
            return piece["source"], piece["in_ms"] + max(
                0, timeline_ms - piece["timeline_start_ms"]
            )
    last = plan["segments"][-1]
    return last["source"], last["out_ms"] - 1


def validate_output(
    tools: MediaTools,
    output: Path,
    plan: dict[str, Any],
    sources: list[Path],
    cancel: threading.Event,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail[:300]})

    target = plan["duration_ms"]
    thresholds = {
        "duration_tolerance_ms": DURATION_TOLERANCE_MS,
        "black_luma": BLACK_LUMA,
        "source_luma": SOURCE_LUMA,
    }
    doc = probe(tools, output, cancel) if output.is_file() and output.stat().st_size else None
    if doc is None:
        for name in ("container", "duration", "video_stream", "decode_start"):
            check(name, False, "The output is empty or not a readable media file.")
        return {
            "passed": False,
            "checks": checks,
            "probe": {"format": "", "duration_ms": 0, "video_streams": 0, "audio_streams": 0},
            "thresholds": thresholds,
        }
    fmt = doc.get("format", {})
    streams = doc.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    try:
        duration_ms = round(float(fmt.get("duration", 0)) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    audit: dict[str, Any] = {
        "format": str(fmt.get("format_name", ""))[:100],
        "duration_ms": duration_ms,
        "video_streams": len(videos),
        "audio_streams": len(audios),
        "tags": sorted(str(k)[:60] for k in (fmt.get("tags") or {}))[:20],
    }
    check("container", "mp4" in audit["format"], f"Container {audit['format'] or 'unknown'}")
    check(
        "duration",
        abs(duration_ms - target) <= DURATION_TOLERANCE_MS,
        f"{duration_ms} ms (target {target} ms, tolerance {DURATION_TOLERANCE_MS} ms)",
    )
    out = plan["output"]
    if len(videos) == 1:
        video = videos[0]
        fps = _fps(video.get("avg_frame_rate"))
        audit["video"] = {
            "codec": str(video.get("codec_name", ""))[:40],
            "width": int(video.get("width", 0)),
            "height": int(video.get("height", 0)),
            "pix_fmt": str(video.get("pix_fmt", ""))[:40],
            "rotation": _rotation(video),
        }
        if video.get("profile"):
            audit["video"]["profile"] = str(video["profile"])[:60]
        if fps is not None:
            audit["video"]["fps"] = {"num": fps.numerator, "den": fps.denominator}
        wanted = Fraction(out["fps"]["num"], out["fps"]["den"])
        check("video_stream", audit["video"]["codec"] == "h264", f"Video {audit['video']['codec']}")
        check(
            "resolution",
            (audit["video"]["width"], audit["video"]["height"]) == (out["width"], out["height"]),
            f"{audit['video']['width']}x{audit['video']['height']}",
        )
        check("pixel_format", audit["video"]["pix_fmt"] == "yuv420p", audit["video"]["pix_fmt"])
        check(
            "frame_rate",
            fps is not None and abs(float(fps / wanted) - 1) <= 0.01,
            f"{float(fps) if fps else 0:.3f} fps (target {float(wanted):.3f})",
        )
        check("rotation", audit["video"]["rotation"] == 0, "Upright, no rotation metadata")
    else:
        check("video_stream", False, f"{len(videos)} video streams (expected 1)")
    if audios:
        a = audios[0]
        audit["audio"] = {
            "codec": str(a.get("codec_name", ""))[:40],
            "channels": int(a.get("channels", 0)),
            "sample_rate_hz": int(a.get("sample_rate", 0) or 0),
        }
    expected_audio = 1 if out["audio"] else 0
    audio_ok = len(audios) == expected_audio and (
        not audios
        or (audit["audio"]["codec"], audit["audio"]["channels"], audit["audio"]["sample_rate_hz"])
        == ("aac", 2, 48000)
    )
    check(
        "audio_stream",
        audio_ok,
        f"{len(audios)} audio streams (expected {expected_audio})"
        + (f", {audit['audio']['codec']}" if audios else ""),
    )
    extra = set(audit["tags"]) - ALLOWED_TAGS
    check(
        "metadata", not extra, "No source metadata copied" if not extra else "Unexpected tags kept"
    )

    ffmpeg = tools.tool("ffmpeg")
    points = {
        "decode_start": min(100, target // 4),
        "decode_middle": target // 2,
        "decode_end": max(0, target - 150),
    }
    black: list[str] = []
    for name, at in points.items():
        luma = _mean_luma(ffmpeg, output, at, cancel)
        check(
            name,
            luma is not None,
            f"Frame at {at} ms decoded" if luma is not None else f"No frame at {at} ms",
        )
        if luma is not None and luma < BLACK_LUMA:
            index, source_ms = source_at(plan, at)
            source_luma = _mean_luma(ffmpeg, sources[index], source_ms, cancel)
            if source_luma is not None and source_luma >= SOURCE_LUMA:
                black.append(f"{at} ms")
    check(
        "black_frames",
        not black,
        "No unexpected black samples"
        if not black
        else "Black where the source is not: " + ", ".join(black),
    )
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "probe": audit,
        "thresholds": thresholds,
    }
