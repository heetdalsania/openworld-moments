# SPDX-License-Identifier: AGPL-3.0-or-later
"""Version 1 macOS media report for native release validation with synthetic clips."""

from __future__ import annotations

import platform
import threading
from pathlib import Path
from typing import Any

from openworld_moments.media.process import ToolCancelled, ToolError, run_tool
from openworld_moments.media.tools import ToolInfo
from openworld_moments.render.encoders import VIDEOTOOLBOX
from openworld_moments.render.service import Renderer

REPORT_VERSION = 1


def probe_decode(tool: ToolInfo, sample: Path, cancel: threading.Event | None = None) -> bool:
    """Require VideoToolbox surfaces and download them before counting a decoded frame."""
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
                "-hwaccel",
                "videotoolbox",
                "-hwaccel_output_format",
                "videotoolbox_vld",
                "-i",
                f"file:{sample}",
                "-an",
                "-sn",
                "-dn",
                "-frames:v",
                "1",
                "-vf",
                "hwdownload,format=nv12,scale=16:16,format=gray",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            timeout_s=20,
            max_stdout=1024,
            cancel=cancel,
        )
    except ToolCancelled:
        raise
    except ToolError:
        return False
    return result.returncode == 0 and len(result.stdout) == 16 * 16


def capability_report(renderer: Renderer, h264: Path, hevc: Path) -> dict[str, Any]:
    tool = renderer.tools.tool("ffmpeg")
    return {
        "report_version": REPORT_VERSION,
        "architecture": platform.machine(),
        "macos_version": platform.mac_ver()[0],
        "ffmpeg_version": tool.version,
        "ffmpeg_libraries": dict(tool.libraries),
        "decode": {"h264": probe_decode(tool, h264), "hevc": probe_decode(tool, hevc)},
        "h264_yuv420p_encode": {
            preset["id"]: next(
                item
                for item in renderer.encoder_status(preset_id=preset["id"])["encoders"]
                if item["id"] == VIDEOTOOLBOX.id
            )
            for preset in renderer.presets.all()
        },
    }
