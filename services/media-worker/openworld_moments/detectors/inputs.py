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
