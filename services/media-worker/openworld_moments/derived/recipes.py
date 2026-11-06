# SPDX-License-Identifier: AGPL-3.0-or-later
"""Presets, FFmpeg argument lists, and cache keys for derived media (M08).

Every artifact has a *recipe*: the preset (with its version), the toolchain
identity, and the concrete output parameters chosen for the asset. The cache
key is the SHA-256 of the asset's SHA-256, the artifact kind, and the recipe as
canonical JSON. Changing a preset version, the FFmpeg build, the policy, or the
tone map changes the key, which makes stored artifacts stale.

All commands are argument lists. Input is ``file:<path>`` with only the
``file`` protocol allowed. FFmpeg runs inside the job's staging folder, so
outputs, the image sequence pattern, and the tone-map LUT are plain relative
names: no user-controlled text ever appears in a filter graph.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments.derived import waveform as wf
from openworld_moments.derived.policy import POLICY_VERSION, ProxyGeometry
from openworld_moments.derived.tonemap import LUT_FILE, ToneMapSettings
from openworld_moments.media.tools import DERIVED_ENCODERS, DERIVED_FILTERS, ToolInfo

PROXY_OUTPUT = "proxy.mp4"
FILMSTRIP_DIR = "filmstrip"
FILMSTRIP_PATTERN = "%04d.jpg"
WAVEFORM_OUTPUT = "waveform.bin"

#: The proxy preset (spec 8.3.2). Bump ``version`` on any change.
PROXY_PRESET: dict[str, Any] = {
    "id": "proxy-h264-sdr",
    "version": 1,
    "video": {
        "encoder": "libx264",
        "preset": "veryfast",
        "crf": 23,
        "profile": "high",
        "pixel_format": "yuv420p",
        # A fixed thread count keeps x264 output identical across machines.
        "threads": 4,
        # A keyframe every second keeps seeking fast (spec 12.4: < 250 ms).
        "keyframe_interval_s": 1,
        "scaler": "bicubic",
    },
    "audio": {"encoder": "aac", "bitrate": "128k", "channels": 2, "sample_rate_hz": 48000},
    "container": "mp4",
    "faststart": True,
}

#: Filmstrip thumbnails: one about every ``interval_s`` seconds, between ``min_count``
#: and ``max_count`` frames, each sampled at the middle of its slice of the asset.
FILMSTRIP_PRESET: dict[str, Any] = {
    "id": "filmstrip-jpeg",
    "version": 1,
    "interval_s": 5,
    "min_count": 1,
    "max_count": 120,
    "max_edge": 160,
    "encoder": "mjpeg",
    "quality": 4,
}

WAVEFORM_PRESET: dict[str, Any] = {
    "id": "waveform-peak-rms",
    "version": 1,
    "format_version": wf.FORMAT_VERSION,
    "sample_rate_hz": wf.SAMPLE_RATE_HZ,
    "buckets_per_second": wf.BUCKETS_PER_SECOND,
    "mix": "mono",
}

#: FFmpeg components every derived artifact needs (also reported by ``doctor``).
REQUIRED_ENCODERS = DERIVED_ENCODERS
REQUIRED_FILTERS = DERIVED_FILTERS


def tool_identity(ffmpeg: ToolInfo) -> dict[str, Any]:
    """What identifies the FFmpeg build in a recipe (not its path)."""
    return {"ffmpeg": ffmpeg.version, "libraries": dict(sorted(ffmpeg.libraries.items()))}


def cache_key(asset_sha256: str, kind: str, recipe: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"asset_sha256": asset_sha256, "kind": kind, "recipe": recipe},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _base(ffmpeg: ToolInfo) -> list[str]:
    return [
        *ffmpeg.command,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-nostats",
        "-protocol_whitelist",
        "file",
    ]


def _bitexact() -> list[str]:
    # No encoder version strings or timestamps in the output: same input → same bytes.
    return ["-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]


# -- proxy ----------------------------------------------------------------------------


def proxy_recipe(
    ffmpeg: ToolInfo,
    geometry: ProxyGeometry,
    *,
    audio: bool,
    source_range: str | None,
    tone_map: ToneMapSettings | None,
) -> dict[str, Any]:
    return {
        "preset": PROXY_PRESET,
        "policy_version": POLICY_VERSION,
        "tool": tool_identity(ffmpeg),
        "output": {
            "width": geometry.width,
            "height": geometry.height,
            "fps_cap": geometry.fps_cap,
            "audio": audio,
            "source_range": source_range or "tv",
        },
        "tone_map": tone_map.describe() if tone_map else None,
    }


def proxy_filter(
    geometry: ProxyGeometry, *, source_range: str | None, tone_map: ToneMapSettings | None
) -> str:
    """The proxy filter graph. Every value comes from validated numbers or constants."""
    scaler = PROXY_PRESET["video"]["scaler"]
    size = f"w={geometry.width}:h={geometry.height}:flags={scaler}"
    steps: list[str]
    if tone_map is None:
        steps = [f"scale={size}", "format=yuv420p"]
    else:
        rng = "pc" if source_range == "pc" else "tv"
        steps = [
            f"scale={size}:in_color_matrix=bt2020:in_range={rng}",
            "format=gbrp16le",
            f"lut3d=file={LUT_FILE}:interp={tone_map.interpolation}",
            f"scale=out_color_matrix=bt709:out_range=tv:flags={scaler}",
            "format=yuv420p",
            "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
        ]
    if geometry.fps_cap is not None:
        steps.append(f"fps=fps={geometry.fps_cap}")
    return ",".join(steps)


def proxy_args(
    ffmpeg: ToolInfo,
    source: Path,
    geometry: ProxyGeometry,
    *,
    audio: bool,
    source_range: str | None,
    tone_map: ToneMapSettings | None,
) -> list[str]:
    video = PROXY_PRESET["video"]
    sound = PROXY_PRESET["audio"]
    args = [
        *_base(ffmpeg),
        "-progress",
        "pipe:1",
        "-i",
        f"file:{source}",
        "-map",
        "0:v:0",
    ]
    if audio:
        args += ["-map", "0:a:0"]
    args += [
        "-vf",
        proxy_filter(geometry, source_range=source_range, tone_map=tone_map),
        "-fps_mode",
        "passthrough" if geometry.fps_cap is None else "cfr",
        "-c:v",
        video["encoder"],
        "-preset",
        video["preset"],
        "-crf",
        str(video["crf"]),
        "-profile:v",
        video["profile"],
        "-pix_fmt",
        video["pixel_format"],
        "-threads",
        str(video["threads"]),
        "-force_key_frames",
        f"expr:gte(t,n_forced*{video['keyframe_interval_s']})",
    ]
    if audio:
        args += [
            "-c:a",
            sound["encoder"],
            "-b:a",
            sound["bitrate"],
            "-ac",
            str(sound["channels"]),
            "-ar",
            str(sound["sample_rate_hz"]),
        ]
    else:
        args += ["-an"]
    args += [
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        *_bitexact(),
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        "-y",
        PROXY_OUTPUT,
    ]
    return args


# -- filmstrip ------------------------------------------------------------------------


@dataclass(frozen=True)
class FilmstripPlan:
    count: int
    times_ms: tuple[int, ...]
    width: int
    height: int


def filmstrip_plan(duration_ms: int, width: int, height: int) -> FilmstripPlan:
    preset = FILMSTRIP_PRESET
    duration_ms = max(1, duration_ms)
    count = -(-duration_ms // (preset["interval_s"] * 1000))
    count = max(preset["min_count"], min(preset["max_count"], count))
    times = tuple((2 * k + 1) * duration_ms // (2 * count) for k in range(count))
    return FilmstripPlan(count, times, width, height)


def filmstrip_recipe(
    ffmpeg: ToolInfo, plan: FilmstripPlan, source: dict[str, Any]
) -> dict[str, Any]:
    return {
        "preset": FILMSTRIP_PRESET,
        "tool": tool_identity(ffmpeg),
        "source": source,
        "output": {"count": plan.count, "width": plan.width, "height": plan.height},
    }


def filmstrip_args(
    ffmpeg: ToolInfo, source: Path, plan: FilmstripPlan, duration_ms: int
) -> list[str]:
    duration_ms = max(1, duration_ms)
    start_ms = plan.times_ms[0]
    graph = ",".join(
        [
            # eof_action=pass: keep the last slice's frame when the clip ends before
            # the next sample point (round=near would wait for one that never comes).
            f"fps=fps={plan.count * 1000}/{duration_ms}:round=near:eof_action=pass",
            f"scale=w={plan.width}:h={plan.height}:flags=bicubic",
        ]
    )
    args = _base(ffmpeg)
    if start_ms > 0:
        args += ["-ss", f"{start_ms / 1000:.3f}"]
    return [
        *args,
        "-i",
        f"file:{source}",
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        graph,
        "-frames:v",
        str(plan.count),
        "-c:v",
        FILMSTRIP_PRESET["encoder"],
        "-q:v",
        str(FILMSTRIP_PRESET["quality"]),
        "-pix_fmt",
        "yuvj420p",
        *_bitexact(),
        "-f",
        "image2",
        "-start_number",
        "1",
        "-y",
        FILMSTRIP_PATTERN,
    ]


# -- waveform -------------------------------------------------------------------------


def waveform_recipe(ffmpeg: ToolInfo) -> dict[str, Any]:
    return {"preset": WAVEFORM_PRESET, "tool": tool_identity(ffmpeg)}


def waveform_args(ffmpeg: ToolInfo, source: Path) -> list[str]:
    return [
        *_base(ffmpeg),
        "-i",
        f"file:{source}",
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        str(wf.SAMPLE_RATE_HZ),
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    ]


# -- sampled validation decode --------------------------------------------------------

LUMA_W, LUMA_H = 32, 18


def luma_args(ffmpeg: ToolInfo, source: Path, at_ms: int) -> list[str]:
    """One tiny grayscale frame at ``at_ms`` (upright: FFmpeg applies rotation)."""
    return [
        *_base(ffmpeg),
        "-ss",
        f"{at_ms / 1000:.3f}",
        "-i",
        f"file:{source}",
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-vf",
        f"scale=w={LUMA_W}:h={LUMA_H}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
