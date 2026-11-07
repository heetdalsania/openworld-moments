# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decode only a checked derived proxy into bounded immutable samples."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from openworld_moments.detectors.sdk import AnalysisError, Frame, checkpoint
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import ToolInfo

WIDTH, HEIGHT, SAMPLE_MS = 64, 36, 500
SAMPLER_VERSION = "gray64x36-2fps-v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024


def content_hash(path: Path, cancel: threading.Event) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            checkpoint(cancel)
            hasher.update(block)
    return hasher.hexdigest()


def decode_frames(path: Path, tool: ToolInfo, cancel: threading.Event) -> tuple[Frame, ...]:
    result = run_tool(
        [
            *tool.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-i",
            f"file:{path}",
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"fps=2,scale={WIDTH}:{HEIGHT}",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        timeout_s=600,
        cancel=cancel,
        max_stdout=MAX_INPUT_BYTES,
    )
    size = WIDTH * HEIGHT
    if result.returncode or not result.stdout or len(result.stdout) % size:
        raise AnalysisError(
            "analysis.decode_failed", "The derived analysis frames could not be decoded."
        )
    checkpoint(cancel)
    return tuple(
        Frame(i // size * SAMPLE_MS, WIDTH, HEIGHT, result.stdout[i : i + size])
        for i in range(0, len(result.stdout), size)
    )


ROI_WIDTH, ROI_HEIGHT = 200, 40
ROI_SAMPLER_VERSION = "gray-roi200x40-2fps-v1"


def decode_region(
    path: Path, tool: ToolInfo, cancel: threading.Event, region: tuple[float, ...]
) -> tuple[Frame, ...]:
    """A fixed built-in ROI sampler; only validated finite numbers enter the filter."""
    import math

    if len(region) != 4 or not all(math.isfinite(v) for v in region):
        raise AnalysisError("analysis.invalid_roi", "A finite normalized ROI is required.")
    x, y, w, h = region
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
        raise AnalysisError("analysis.invalid_roi", "The ROI must fit within the picture.")
    graph = (
        f"fps=2,format=gray,crop=w=iw*{w:.12f}:h=ih*{h:.12f}:"
        f"x=iw*{x:.12f}:y=ih*{y:.12f}:exact=1,"
        f"scale={ROI_WIDTH}:{ROI_HEIGHT}:flags=area"
    )
    result = run_tool(
        [
            *tool.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-i",
            f"file:{path}",
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            graph,
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        timeout_s=600,
        cancel=cancel,
        max_stdout=MAX_INPUT_BYTES,
    )
    size = ROI_WIDTH * ROI_HEIGHT
    if result.returncode or not result.stdout or len(result.stdout) % size:
        raise AnalysisError(
            "analysis.decode_failed", "The derived ROI samples could not be decoded."
        )
    checkpoint(cancel)
    return tuple(
        Frame(i // size * SAMPLE_MS, ROI_WIDTH, ROI_HEIGHT, result.stdout[i : i + size], region)
        for i in range(0, len(result.stdout), size)
    )


def require_roi_detail(width: int, height: int, region: tuple[float, ...], maximum: int) -> None:
    """The current M08 proxy must preserve at least 12 pixels per indicator and in height."""
    from openworld_moments.derived.policy import PROXY_MAX_EDGE, fit

    proxy_width, proxy_height = fit(width, height, PROXY_MAX_EDGE)
    if int(proxy_width * region[2]) < maximum * 12 or int(proxy_height * region[3]) < 12:
        raise AnalysisError(
            "profile.incompatible", "regions: the playback copy's indicator crop is too small"
        )
