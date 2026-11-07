# SPDX-License-Identifier: AGPL-3.0-or-later
"""CPU benchmark for the deterministic audio features (excludes decode and I/O)."""

from __future__ import annotations

import os
import platform
import statistics
import sys
import time
from typing import Any

from openworld_moments.detectors.audio import features
from openworld_moments.detectors.audio_fixtures import mixed_minute, samples
from openworld_moments.detectors.sdk import AudioSamples


def benchmark(minutes: int = 10, repeats: int = 3) -> dict[str, Any]:
    if not 1 <= minutes <= 120 or not 1 <= repeats <= 10:
        raise ValueError("minutes must be 1-120 and repeats 1-10")
    minute = samples(mixed_minute())
    audio = AudioSamples(minute.sample_rate, minute.full * minutes, minute.speech_band * minutes)
    duration_ms = minutes * 60_000
    timings, counts = [], {}
    for _ in range(repeats):
        start = time.perf_counter()
        found = features(audio, duration_ms)
        timings.append(time.perf_counter() - start)
        counts = {k: sum(1 for f in found if f.kind == k) for k in sorted({f.kind for f in found})}
    median = statistics.median(timings)
    return {
        "audio_minutes": minutes,
        "repeats": repeats,
        "seconds": [round(t, 3) for t in timings],
        "median_seconds": round(median, 3),
        "realtime_factor": round(duration_ms / 1000 / median, 1),
        "budget_2x_met": median * 2 <= duration_ms / 1000,
        "features": counts,
        "machine": {
            "platform": platform.platform(),
            "processor": platform.machine(),
            "cpus": os.cpu_count(),
            "python": sys.version.split()[0],
        },
        "scope": "feature extraction only; excludes proxy creation, FFmpeg decode and I/O",
    }
