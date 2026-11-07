# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decode only a checked derived proxy's first audio stream into bounded analysis PCM.

The graph is fixed source code: mono 8 kHz signed 16-bit, as two channels, the full
band and a 300-3400 Hz speech band. No profile value reaches FFmpeg.
"""

from __future__ import annotations

import sys
import threading
from array import array
from pathlib import Path

from openworld_moments.detectors.sdk import AnalysisError, AudioSamples, checkpoint
from openworld_moments.media.process import ToolOutputTooLarge, run_tool
from openworld_moments.media.tools import ToolInfo

SAMPLE_RATE = 8000
AUDIO_SAMPLER_VERSION = "pcm8k-mono-speechband-v1"
#: Two 16-bit channels at 8 kHz: about 35 minutes of audio per clip.
MAX_AUDIO_BYTES = 64 * 1024 * 1024
GRAPH = (
    f"[0:a:0]aresample={SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono,"
    "asplit=2[full][band];"
    "[band]highpass=f=300:poles=2,lowpass=f=3400:poles=2[speech];"
    "[full][speech]amerge=inputs=2[out]"
)


def track_policy(audio_streams: int) -> str:
    """Analysis uses the first audio stream, like the proxy, waveform and fingerprints."""
    return "none" if audio_streams <= 0 else f"first-of-{audio_streams}"


def decode_audio(path: Path, tool: ToolInfo, cancel: threading.Event) -> AudioSamples:
    try:
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
                "-filter_complex",
                GRAPH,
                "-map",
                "[out]",
                "-vn",
                "-f",
                "s16le",
                "pipe:1",
            ],
            timeout_s=600,
            cancel=cancel,
            max_stdout=MAX_AUDIO_BYTES,
        )
    except ToolOutputTooLarge as exc:
        raise AnalysisError(
            "analysis.audio_too_long",
            "This clip is longer than the audio analysis limit (about 35 minutes).",
        ) from exc
    if result.returncode or len(result.stdout) % 4:
        raise AnalysisError(
            "analysis.decode_failed", "The derived analysis audio could not be decoded."
        )
    checkpoint(cancel)
    return split_channels(result.stdout, SAMPLE_RATE)


def split_channels(interleaved: bytes, sample_rate: int) -> AudioSamples:
    """De-interleave (full, speech band) little-endian 16-bit samples."""
    samples = array("h")
    samples.frombytes(interleaved)
    if sys.byteorder != "little":  # pragma: no cover - every supported platform is LE
        samples.byteswap()
    full, band = samples[0::2], samples[1::2]
    if sys.byteorder != "little":  # pragma: no cover
        full.byteswap()
        band.byteswap()
    return AudioSamples(sample_rate, full.tobytes(), band.tobytes())
