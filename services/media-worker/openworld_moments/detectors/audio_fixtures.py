# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic analysis audio for tests and benchmarks: tones, impacts, silence and a
speech-like signal (harmonic voice at a syllabic rate). Generated, never recorded."""

from __future__ import annotations

import math
import random
from array import array

from openworld_moments.detectors.audio_input import SAMPLE_RATE
from openworld_moments.detectors.sdk import AudioSamples


def _pcm(values: list[float]) -> bytes:
    return array("h", [max(-32767, min(32767, round(v))) for v in values]).tobytes()


def silence(seconds: float) -> list[float]:
    return [0.0] * round(seconds * SAMPLE_RATE)


def tone(seconds: float, hz: float = 440.0, amplitude: float = 0.5) -> list[float]:
    return [
        amplitude * 32767 * math.sin(2 * math.pi * hz * i / SAMPLE_RATE)
        for i in range(round(seconds * SAMPLE_RATE))
    ]


def noise_floor(seconds: float, level: float = 30.0, seed: int = 1) -> list[float]:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic signal, not security
    return [rng.gauss(0, level) for _ in range(round(seconds * SAMPLE_RATE))]


def add_impact(signal: list[float], at_s: float, peak: float = 20000.0, seed: int = 7) -> None:
    """A broadband transient decaying with a 15 ms time constant over 80 ms."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic signal, not security
    start = round(at_s * SAMPLE_RATE)
    for k in range(start, min(len(signal), start + round(0.08 * SAMPLE_RATE))):
        signal[k] += peak * math.exp(-(k - start) / (0.015 * SAMPLE_RATE)) * rng.uniform(-1, 1)


def speech_like(seconds: float, f0: float = 140.0, syllables_hz: float = 4.0) -> list[float]:
    """Harmonics 280 Hz-2.7 kHz of a 140 Hz voice, amplitude-modulated at a syllabic rate."""
    out = []
    for i in range(round(seconds * SAMPLE_RATE)):
        t = i / SAMPLE_RATE
        envelope = max(0.0, math.sin(2 * math.pi * syllables_hz * t)) ** 2
        voice = sum(math.sin(2 * math.pi * f0 * h * t) / h for h in range(2, 20))
        out.append(8000 * envelope * voice)
    return out


def speech_band(signal: list[float]) -> list[float]:
    """A deterministic two-pole 300-3400 Hz band-pass, close to the FFmpeg graph's."""

    def biquad(values: list[float], b: tuple[float, ...], a: tuple[float, ...]) -> list[float]:
        x1 = x2 = y1 = y2 = 0.0
        out = []
        for x in values:
            y = b[0] * x + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
            x2, x1, y2, y1 = x1, x, y1, y
            out.append(y)
        return out

    def coefficients(kind: str, f: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
        w = 2 * math.pi * f / SAMPLE_RATE
        alpha = math.sin(w) / (2 * 0.7071)
        cos = math.cos(w)
        if kind == "high":
            b = ((1 + cos) / 2, -(1 + cos), (1 + cos) / 2)
        else:
            b = ((1 - cos) / 2, 1 - cos, (1 - cos) / 2)
        a0 = 1 + alpha
        return tuple(v / a0 for v in b), (1.0, -2 * cos / a0, (1 - alpha) / a0)

    return biquad(biquad(signal, *coefficients("high", 300)), *coefficients("low", 3400))


def samples(signal: list[float]) -> AudioSamples:
    return AudioSamples(SAMPLE_RATE, _pcm(signal), _pcm(speech_band(signal)))


def mixed_minute(seed: int = 3) -> list[float]:
    """One minute alternating speech-like passages, tones, impacts and silence."""
    signal: list[float] = []
    for block in range(6):
        signal += noise_floor(2, seed=seed + block)
        signal += speech_like(3)
        signal += tone(2, 220 + 40 * block, 0.3)
        signal += silence(3)
    for at in (1.0, 13.5, 27.25, 44.0):
        add_impact(signal, at)
    return signal
