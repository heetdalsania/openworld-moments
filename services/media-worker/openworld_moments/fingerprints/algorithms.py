# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fingerprint algorithms (M06). Pure functions plus bounded FFmpeg decodes.

Every algorithm has a name and an integer version, persisted with its output.
Changing the computation of an algorithm requires bumping its version: stored
rows with an older version are then stale and recomputed by the backfill job.

* ``owm-fast`` v1: SHA-256 over the size (8 bytes, little-endian) and the
  first and last MiB. Reads at most 2 MiB.
* ``dhash256`` v1: FFmpeg samples ``SAMPLE_FPS`` frames per second over the first
  and last ``WINDOW_MS`` of the video, scales each to 17x16 grayscale (area
  filter, after automatic rotation), and each row yields 16 bits: left pixel
  brighter than its right neighbour. (9x8 / 64 bits was too coarse: two
  segments of a mostly static scene matched; 17x16 separates them while a
  heavy re-encode stays within the match distance.) A frame whose brightest and darkest pixels
  differ by at most ``FLAT_RANGE`` is flagged ``flat`` and ignored in matching.
* ``energy-envelope`` v1: the first audio stream, mixed to mono at 8 kHz, as
  ``ENVELOPE_RATE_HZ`` loudness values per second in 0.5 dB steps (0 = silence
  or below -127.5 dBFS, 255 = full scale) over the same windows.
* ``perceptual-match`` v1: see :func:`compare_frames`.
"""

from __future__ import annotations

import hashlib
import math
import struct
import sys
import threading
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments.media.process import (
    ToolCancelled,
    ToolNotStarted,
    ToolOutputTooLarge,
    ToolTimeout,
    run_tool,
)
from openworld_moments.media.tools import ToolInfo
from openworld_moments.redaction import Redactor

FAST_ALGORITHM, FAST_VERSION = "owm-fast", 1
FRAMES_ALGORITHM, FRAMES_VERSION = "dhash256", 1
AUDIO_ALGORITHM, AUDIO_VERSION = "energy-envelope", 1
MATCH_ALGORITHM, MATCH_VERSION = "perceptual-match", 1

FAST_SPAN = 1024 * 1024
WINDOW_MS = 30_000
SAMPLE_FPS = 2
FLAT_RANGE = 8
ENVELOPE_RATE_HZ = 10
AUDIO_SAMPLE_RATE = 8000
DECODE_TIMEOUT_S = 180.0

HASH_W, HASH_H = 17, 16
HASH_BITS = (HASH_W - 1) * HASH_H  # 256
#: Two frames match when at most this many of their 256 bits differ (about 9%).
MATCH_MAX_DISTANCE = 24
#: A pair becomes a candidate with at least this many informative frame pairs...
MATCH_MIN_FRAMES = 4
#: ...of which at least this fraction match...
MATCH_MIN_RATIO = 0.8
#: ...and durations differing by at most max(this many ms, MATCH_DURATION_RATIO).
MATCH_DURATION_SLACK_MS = 1000
MATCH_DURATION_RATIO = 0.02

_FRAME_BYTES = HASH_W * HASH_H


class DecodeError(Exception):
    """FFmpeg could not decode a window. ``code`` is stable; no path in ``message``."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, stderr_tail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.stderr_tail = stderr_tail


class DecodeCancelled(Exception):
    pass


# -- exact and fast hashes ------------------------------------------------------------


def fast_hash(path: Path, size: int) -> str:
    """``owm-fast`` v1 of a file of ``size`` bytes (read-only, at most 2 MiB)."""
    digest = hashlib.sha256(struct.pack("<Q", size))
    with path.open("rb") as handle:
        digest.update(handle.read(FAST_SPAN))
        if size > FAST_SPAN:
            handle.seek(max(FAST_SPAN, size - FAST_SPAN))
            digest.update(handle.read(FAST_SPAN))
    return digest.hexdigest()


# -- windows --------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    start_ms: int
    length_ms: int


def windows(duration_ms: int, window_ms: int = WINDOW_MS) -> tuple[Window, Window]:
    """Head and tail windows. They are the same window when the asset is short."""
    length = max(1, min(window_ms, duration_ms))
    return Window(0, length), Window(max(0, duration_ms - length), length)


def _input_args(ffmpeg: ToolInfo, path: Path, window: Window) -> list[str]:
    return [
        *ffmpeg.command,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file",
        "-ss",
        f"{window.start_ms / 1000:.3f}",
        "-t",
        f"{window.length_ms / 1000:.3f}",
        "-i",
        f"file:{path}",
    ]


def _decode(
    argv: list[str], path: Path, *, cancel: threading.Event | None, max_out: int, timeout_s: float
) -> bytes:
    try:
        result = run_tool(
            argv,
            timeout_s=timeout_s,
            cancel=cancel,
            max_stdout=max_out,
            redactor=Redactor([str(path)]),
        )
    except ToolCancelled as exc:
        raise DecodeCancelled from exc
    except ToolTimeout as exc:
        raise DecodeError(
            "fingerprint.decode_timeout",
            f"Decoding did not finish within {timeout_s:g} seconds.",
            retryable=True,
            stderr_tail=exc.stderr_tail,
        ) from exc
    except ToolOutputTooLarge as exc:
        raise DecodeError(
            "fingerprint.decode_failed", "The decoder produced more output than expected."
        ) from exc
    except ToolNotStarted as exc:
        raise DecodeError(
            "tool.ffmpeg_unusable", "FFmpeg could not be started.", retryable=True
        ) from exc
    if result.returncode != 0:
        raise DecodeError(
            "fingerprint.decode_failed",
            "FFmpeg could not decode the sampled part of the file.",
            stderr_tail=result.stderr_tail,
        )
    return result.stdout


# -- frames ---------------------------------------------------------------------------


def dhash(pixels: bytes) -> tuple[str, bool]:
    """``dhash256`` of one 17x16 grayscale frame: (64 hex digits, flat)."""
    if len(pixels) != _FRAME_BYTES:
        raise ValueError("expected a 17x16 grayscale frame")
    bits = 0
    for row in range(HASH_H):
        base = row * HASH_W
        for col in range(HASH_W - 1):
            bits = (bits << 1) | (pixels[base + col] > pixels[base + col + 1])
    return f"{bits:064x}", max(pixels) - min(pixels) <= FLAT_RANGE


def frame_hashes(
    ffmpeg: ToolInfo,
    path: Path,
    window: Window,
    *,
    cancel: threading.Event | None = None,
    timeout_s: float = DECODE_TIMEOUT_S,
) -> list[dict[str, Any]]:
    argv = [
        *_input_args(ffmpeg, path, window),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={SAMPLE_FPS},scale={HASH_W}:{HASH_H}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    expected = math.ceil(window.length_ms / 1000 * SAMPLE_FPS) + 2
    raw = _decode(argv, path, cancel=cancel, max_out=expected * _FRAME_BYTES, timeout_s=timeout_s)
    step_ms = 1000 // SAMPLE_FPS
    out: list[dict[str, Any]] = []
    for i in range(len(raw) // _FRAME_BYTES):
        value, flat = dhash(raw[i * _FRAME_BYTES : (i + 1) * _FRAME_BYTES])
        frame: dict[str, Any] = {"t_ms": window.start_ms + i * step_ms, "hash": value}
        if flat:
            frame["flat"] = True
        out.append(frame)
    return out


# -- audio ----------------------------------------------------------------------------


def envelope(samples: Sequence[int], rate: int = AUDIO_SAMPLE_RATE) -> list[int]:
    """``energy-envelope`` values for signed 16-bit mono samples."""
    block = rate // ENVELOPE_RATE_HZ
    out: list[int] = []
    for start in range(0, len(samples) - block + 1, block):
        chunk = samples[start : start + block]
        mean_square = sum(s * s for s in chunk) / block
        if mean_square <= 0:
            out.append(0)
            continue
        db = 10 * math.log10(mean_square / (32768.0 * 32768.0))
        out.append(max(0, min(255, round((db + 127.5) * 2))))
    return out


def audio_envelope(
    ffmpeg: ToolInfo,
    path: Path,
    window: Window,
    *,
    cancel: threading.Event | None = None,
    timeout_s: float = DECODE_TIMEOUT_S,
) -> list[int]:
    argv = [
        *_input_args(ffmpeg, path, window),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]
    max_out = (window.length_ms // 1000 + 2) * AUDIO_SAMPLE_RATE * 2
    raw = _decode(argv, path, cancel=cancel, max_out=max_out, timeout_s=timeout_s)
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return envelope(samples)


# -- comparison -----------------------------------------------------------------------


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


@dataclass(frozen=True)
class Match:
    score: float
    evidence: dict[str, Any]


def compare_frames(
    a: dict[str, Any], b: dict[str, Any], duration_a: int, duration_b: int
) -> Match | None:
    """``perceptual-match`` v1: are two assets the same content?

    Head is compared with head and tail with tail, frame by frame in sampling
    order; flat frames are skipped. Comparing like with like means a replay
    overlap (A's tail repeated as B's head) is not a duplicate: that is M12's
    alignment problem. Returns None unless the pair qualifies (see constants).
    Score = matching ratio x (1 - mean distance / (2 x MATCH_MAX_DISTANCE)), so
    identical frames score 1 and frames at the match limit score 0.5.
    """
    delta = abs(duration_a - duration_b)
    if delta > max(MATCH_DURATION_SLACK_MS, MATCH_DURATION_RATIO * max(duration_a, duration_b)):
        return None
    compared = matching = total = 0
    for side in ("head", "tail"):
        for fa, fb in zip(a.get(side, []), b.get(side, []), strict=False):
            if fa.get("flat") or fb.get("flat"):
                continue
            distance = hamming(fa["hash"], fb["hash"])
            compared += 1
            total += distance
            matching += distance <= MATCH_MAX_DISTANCE
    if compared < MATCH_MIN_FRAMES or matching / compared < MATCH_MIN_RATIO:
        return None
    mean = total / compared
    score = round((matching / compared) * max(0.0, 1 - mean / (2 * MATCH_MAX_DISTANCE)), 4)
    return Match(
        score,
        {
            "compared_frames": compared,
            "matching_frames": matching,
            "mean_distance": round(mean, 3),
            "max_distance": MATCH_MAX_DISTANCE,
            "duration_delta_ms": delta,
        },
    )


def correlation(x: Sequence[int], y: Sequence[int]) -> float | None:
    """Pearson correlation of two envelopes over their common length; None if undefined."""
    n = min(len(x), len(y))
    if n < 3:
        return None
    xs, ys = x[:n], y[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((v - mx) ** 2 for v in xs)
    syy = sum((v - my) ** 2 for v in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((u - mx) * (v - my) for u, v in zip(xs, ys, strict=True))
    return max(-1.0, min(1.0, round(sxy / math.sqrt(sxx * syy), 4)))
