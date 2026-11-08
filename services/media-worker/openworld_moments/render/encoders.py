# SPDX-License-Identifier: AGPL-3.0-or-later
"""H.264 encoders: CPU libx264 always; hardware encoders only after a real test encode
(spec 11.3). Brand names or GPU presence never make an encoder available.

Hardware encoders have their own quality scales. Each has a documented mapping from
the preset's x264 CRF and a ``quality_note`` shown before rendering, so a hardware
choice never silently changes quality expectations.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
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
            "VideoToolbox quality (-q:v) approximates x264 CRF; file size and detail can differ.",
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
        args = ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-pix_fmt", "yuv420p"]
        args += ["-q:v", str(videotoolbox_quality(crf))] if crf is not None else rate
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


PROBE_PRESET: dict[str, Any] = {"video": {"codec": "h264", "crf": 23}}


class EncoderProbe:
    """Which encoders work with this FFmpeg, by actually encoding half a second."""

    def __init__(self, specs: dict[str, EncoderSpec] | None = None) -> None:
        self.specs = specs or ENCODERS
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def status(self, tool: ToolInfo, *, refresh: bool = False) -> list[dict[str, Any]]:
        key = tool.version or "unknown"
        with self._lock:
            if refresh or key not in self._cache:
                self._cache[key] = self._probe(tool)
            return [dict(s) for s in self._cache[key]]

    def _probe(self, tool: ToolInfo) -> list[dict[str, Any]]:
        try:
            listing = run_tool(
                [*tool.command, "-hide_banner", "-encoders"], timeout_s=20, max_stdout=1024 * 1024
            ).stdout.decode("utf-8", errors="replace")
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
            elif self.test_encode(tool, spec):
                entry["available"] = True
            else:
                entry["reason"] = (
                    "The test encode failed on this computer (no supported hardware or driver)."
                    if spec.kind == "hardware"
                    else "The test encode failed."
                )
            statuses.append(entry)
        return statuses

    @staticmethod
    def test_encode(tool: ToolInfo, spec: EncoderSpec) -> bool:
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
                    "testsrc2=size=320x240:rate=30:duration=0.5",
                    *video_args(spec, PROBE_PRESET),
                    "-f",
                    "null",
                    "-",
                ],
                timeout_s=20,
                max_stdout=64 * 1024,
            )
        except ToolCancelled:
            raise
        except ToolError:
            return False
        return result.returncode == 0
