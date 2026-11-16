# SPDX-License-Identifier: AGPL-3.0-or-later
"""H.264 encoders: CPU libx264 always; hardware encoders only after a real test encode
(spec 11.3). Brand names or GPU presence never make an encoder available.

Hardware encoders have their own quality scales. Each has a documented mapping from
the preset's x264 CRF and a ``quality_note`` shown before rendering, so a hardware
choice never silently changes quality expectations.
"""

from __future__ import annotations

import platform
import re
import sys
import threading
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from openworld_moments.media.process import ToolCancelled, ToolError, run_tool
from openworld_moments.media.tools import ToolInfo


@dataclass(frozen=True)
class EncoderSpec:
    id: str
    label: str
    kind: str  # cpu | hardware
    codec: str  # the FFmpeg encoder name
    quality_note: str = ""
    #: Extra arguments, used by tests to model a hardware encoder that fails mid-render.
    extra: tuple[str, ...] = ()


ENCODERS: dict[str, EncoderSpec] = {
    spec.id: spec
    for spec in (
        EncoderSpec("libx264", "CPU (libx264)", "cpu", "libx264"),
        EncoderSpec(
            "h264_videotoolbox",
            "Apple VideoToolbox",
            "hardware",
            "h264_videotoolbox",
            "VideoToolbox approximates x264 quality using Apple quality controls or an Intel "
            "bitrate target. File size and detail can differ.",
        ),
        EncoderSpec(
            "h264_nvenc",
            "NVIDIA NVENC",
            "hardware",
            "h264_nvenc",
            "NVENC constant quality (-cq) approximates x264 CRF; file size and detail can differ.",
        ),
        EncoderSpec(
            "h264_qsv",
            "Intel Quick Sync",
            "hardware",
            "h264_qsv",
            "Quick Sync global quality approximates x264 CRF; file size and detail can differ.",
        ),
        EncoderSpec(
            "h264_amf",
            "AMD AMF",
            "hardware",
            "h264_amf",
            "AMF constant QP approximates x264 CRF; file size and detail can differ.",
        ),
    )
}
CPU = ENCODERS["libx264"]
VIDEOTOOLBOX = ENCODERS["h264_videotoolbox"]
PROBE_PRESET: dict[str, Any] = {
    "width": 1920,
    "height": 1080,
    "fps": {"num": 30, "den": 1},
    "video": {"codec": "h264", "crf": 23},
}


def videotoolbox_target(preset: dict[str, Any]) -> str | None:
    """Bound the probe to fixed-rate 8-bit H.264 SDR outputs up to 1080p60."""
    w, h = preset["width"], preset["height"]
    fps = preset["fps"]
    if (
        preset["video"]["codec"] != "h264"
        or max(w, h) > 1920
        or min(w, h) > 1080
        or fps == "source"
    ):
        return None
    rate = Fraction(fps["num"], fps["den"])
    if not 1 <= rate <= 60:
        return None
    frames = max(2, round(rate / 2))
    return f"testsrc2=size={w}x{h}:rate={rate.numerator}/{rate.denominator},trim=end_frame={frames}"


def videotoolbox_quality(crf: int) -> int:
    """x264 CRF 0-51 to VideoToolbox -q:v 1-100 (higher is better): CRF 20 -> 65."""
    return max(1, min(100, round(100 - crf * 1.75)))


def video_args(spec: EncoderSpec, preset: dict[str, Any]) -> list[str]:
    video = preset["video"]
    crf, kbps = video.get("crf"), video.get("bitrate_kbps")
    rate = (
        ["-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]
        if kbps is not None
        else []
    )
    args: list[str]
    if spec.codec == "libx264":
        args = ["-c:v", "libx264", "-preset", "medium", "-profile:v", "high"]
        args += ["-crf", str(crf)] if crf is not None else rate
        args += ["-pix_fmt", "yuv420p"]
    elif spec.codec == "h264_videotoolbox":
        args = [
            "-c:v",
            "h264_videotoolbox",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-allow_sw",
            "0",
        ]
        if crf is None:
            args += rate
        elif sys.platform == "darwin" and platform.machine() == "x86_64":
            # FFmpeg's VideoToolbox constant-quality option is Apple Silicon only.
            # Approximate the preset using a bounded bitrate scaled by pixel rate.
            size = preset.get("width", 1920) * preset.get("height", 1080)
            fps = preset.get("fps", PROBE_PRESET["fps"])
            frame_rate = fps["num"] / fps["den"] if isinstance(fps, dict) else 30
            target = round(12_000 * size / (1920 * 1080) * frame_rate / 30 * 2 ** ((20 - crf) / 6))
            args += ["-b:v", f"{max(128, min(50_000, target))}k"]
        else:
            args += ["-q:v", str(videotoolbox_quality(crf))]
    elif spec.codec == "h264_nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", "p5", "-profile:v", "high", "-pix_fmt", "yuv420p"]
        args += ["-rc", "vbr", "-cq", str(crf), "-b:v", "0"] if crf is not None else rate
    elif spec.codec == "h264_qsv":
        args = ["-c:v", "h264_qsv", "-profile:v", "high"]
        args += ["-global_quality", str(crf)] if crf is not None else rate
    else:  # h264_amf
        args = ["-c:v", "h264_amf", "-quality", "quality", "-profile:v", "high"]
        args += ["-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)] if crf is not None else rate
    return [*args, *spec.extra]


class EncoderProbe:
    """Which encoders work with this FFmpeg, by actually encoding half a second."""

    def __init__(self, specs: dict[str, EncoderSpec] | None = None) -> None:
        self.specs = specs or ENCODERS
        self._cache: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def status(
        self,
        tool: ToolInfo,
        *,
        refresh: bool = False,
        preset: dict[str, Any] | None = None,
        cancel: threading.Event | None = None,
    ) -> list[dict[str, Any]]:
        preset = preset or PROBE_PRESET
        target = videotoolbox_target(preset)
        options = tuple(video_args(VIDEOTOOLBOX, preset)) if target is not None else ()
        key = (tool.command, tool.version, tuple(sorted(tool.libraries.items())), target, options)
        with self._lock:
            if refresh or key not in self._cache:
                statuses = self._probe(tool, target, options, cancel)
                if key not in self._cache and len(self._cache) >= 32:
                    del self._cache[next(iter(self._cache))]
                self._cache[key] = statuses
            return [dict(s) for s in self._cache[key]]

    def _probe(
        self,
        tool: ToolInfo,
        target: str | None,
        options: tuple[str, ...],
        cancel: threading.Event | None,
    ) -> list[dict[str, Any]]:
        try:
            listing = run_tool(
                [*tool.command, "-hide_banner", "-encoders"],
                timeout_s=20,
                max_stdout=1024 * 1024,
                cancel=cancel,
            ).stdout.decode("utf-8", errors="replace")
        except ToolCancelled:
            raise
        except ToolError:
            listing = ""
        built = set(re.findall(r"^\s*V\S*\s+(\S+)", listing, flags=re.MULTILINE))
        statuses = []
        for spec in self.specs.values():
            entry: dict[str, Any] = {
                "id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "available": False,
            }
            if spec.quality_note:
                entry["quality_note"] = spec.quality_note
            if spec.codec not in built:
                entry["reason"] = "Not built into this FFmpeg."
            elif spec.id == VIDEOTOOLBOX.id and target is None:
                entry["reason"] = "Choose the CPU encoder for this size or source frame rate."
            elif self.test_encode(tool, spec, target, options, cancel):
                entry["available"] = True
            else:
                entry["reason"] = (
                    "The test encode failed for this preset. Choose the CPU encoder."
                    if spec.id == VIDEOTOOLBOX.id
                    else "The test encode failed (no supported hardware or driver)."
                    if spec.kind == "hardware"
                    else "The test encode failed."
                )
            statuses.append(entry)
        return statuses

    @staticmethod
    def test_encode(
        tool: ToolInfo,
        spec: EncoderSpec,
        target: str | None,
        options: tuple[str, ...],
        cancel: threading.Event | None,
    ) -> bool:
        is_vt = spec.id == VIDEOTOOLBOX.id
        source = target if is_vt else "testsrc2=size=320x240:rate=30:duration=0.5"
        if source is None:
            return False
        args = (
            ["+yuv420p" if a == "yuv420p" else a for a in options]
            if is_vt
            else video_args(spec, PROBE_PRESET)
        )
        try:
            result = run_tool(
                [
                    *tool.command,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-f",
                    "lavfi",
                    "-i",
                    source,
                    *args,
                    "-f",
                    "null",
                    "-",
                ],
                timeout_s=20,
                max_stdout=64 * 1024,
                cancel=cancel,
            )
        except ToolCancelled:
            raise
        except ToolError:
            return False
        return result.returncode == 0
