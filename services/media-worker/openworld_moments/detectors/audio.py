# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic audio features (M18): loudness envelope, onsets/impacts, silence and
speech-like activity. Every output is *supporting evidence*, never a highlight claim.

All features derive from 10 ms hop energies of the two analysis channels (full band
and 300-3400 Hz speech band). Levels are RMS in dBFS: a full-scale sine is about
-3 dBFS, digital silence is floored at -160 dBFS. See docs/detectors/audio.md.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from openworld_moments.detectors.sdk import AnalysisContext, AudioSamples, Detection

HOP_MS = 10
BLOCK_HOPS = 10  # 100 ms envelope blocks
FLOOR_DBFS = -160.0
FULL_SCALE = 32768.0 * 32768.0

# Silence: every 100 ms block below the threshold for at least a second.
SILENCE_DBFS = -50.0
MIN_SILENCE_MS = 1000

# Onsets: a jump of at least ONSET_RISE_DB over the loudest of the previous 50 ms,
# reaching ONSET_MIN_DBFS. An onset that falls back by IMPACT_DECAY_DB within
# 300 ms is an impact (a short transient); otherwise a sustained onset.
ONSET_LOOKBACK_HOPS = 5
ONSET_RISE_DB = 15.0
ONSET_MIN_DBFS = -40.0
PEAK_SEARCH_HOPS = 5
DECAY_WINDOW_HOPS = 30
IMPACT_DECAY_DB = 12.0
REFRACTORY_HOPS = 15

# Speech-like activity: blocks loud enough with most energy in the speech band, over
# at least 600 ms (gaps up to 300 ms bridged), with syllable-like modulation.
SPEECH_MIN_DBFS = -45.0
SPEECH_BAND_RATIO = 0.45
SPEECH_GAP_BLOCKS = 3
SPEECH_MIN_BLOCKS = 6
SPEECH_MODULATION_DB = 3.0
SYLLABLE_RISE_DB = 6.0
SYLLABLE_MIN_HZ, SYLLABLE_MAX_HZ = 1.5, 10.0


def level_db(energy: float) -> float:
    if energy <= 0:
        return FLOOR_DBFS
    return max(FLOOR_DBFS, 10 * math.log10(energy / FULL_SCALE))


def hop_energies(pcm: bytes, sample_rate: int, check: Callable[[], None]) -> list[float]:
    """Mean-square energy of each 10 ms hop (the last partial hop included)."""
    samples = array("h")
    samples.frombytes(pcm)
    hop = sample_rate * HOP_MS // 1000
    energies = []
    for index, start in enumerate(range(0, len(samples), hop)):
        if index % 6000 == 0:  # every minute of audio
            check()
        chunk = samples[start : start + hop]
        energies.append(math.sumprod(chunk, chunk) / len(chunk))
    return energies


def envelope(energies: list[float]) -> list[float]:
    """Loudness envelope: RMS level in dBFS of each 100 ms block."""
    return [
        level_db(math.fsum(energies[i : i + BLOCK_HOPS]) / len(energies[i : i + BLOCK_HOPS]))
        for i in range(0, len(energies), BLOCK_HOPS)
    ]


@dataclass(frozen=True)
class Feature:
    """One supporting-evidence interval in source milliseconds."""

    kind: str  # impact | onset | silence | speech_activity
    start_ms: int
    end_ms: int
    confidence: float
    level_dbfs: float
    details: tuple[tuple[str, float], ...] = ()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def silences(blocks: list[float], duration_ms: int) -> Iterator[Feature]:
    run: list[int] = []
    for index in [*range(len(blocks)), None]:
        if index is not None and blocks[index] < SILENCE_DBFS:
            run.append(index)
            continue
        if run and len(run) * BLOCK_HOPS * HOP_MS >= MIN_SILENCE_MS:
            loudest = max(blocks[i] for i in run)
            yield Feature(
                "silence",
                run[0] * BLOCK_HOPS * HOP_MS,
                min(duration_ms, (run[-1] + 1) * BLOCK_HOPS * HOP_MS),
                round(_clamp(0.5 + (SILENCE_DBFS - loudest) / 40, 0.5, 1.0), 3),
                round(loudest, 2),
            )
        run = []


def onsets(levels: list[float], duration_ms: int) -> Iterator[Feature]:
    index = ONSET_LOOKBACK_HOPS
    while index < len(levels):
        before = max(levels[index - ONSET_LOOKBACK_HOPS : index])
        rise = levels[index] - before
        if rise < ONSET_RISE_DB or levels[index] < ONSET_MIN_DBFS:
            index += 1
            continue
        window = levels[index : index + PEAK_SEARCH_HOPS + 1]
        peak = index + window.index(max(window))
        peak_db = levels[peak]
        end = min(len(levels), peak + DECAY_WINDOW_HOPS + 1)
        kind = "onset"
        for later in range(peak + 1, end):
            if levels[later] <= peak_db - IMPACT_DECAY_DB:
                kind, end = "impact", later
                break
        rise = peak_db - before
        yield Feature(
            kind,
            index * HOP_MS,
            min(duration_ms, max(end, index + 1) * HOP_MS),
            round(_clamp(0.5 + (rise - ONSET_RISE_DB) / 50, 0.5, 0.9), 3),
            round(peak_db, 2),
            (("rise_db", round(rise, 2)),),
        )
        index = peak + REFRACTORY_HOPS


def _syllable_rate(band_levels: list[float]) -> float:
    """Syllable-like peaks per second: local maxima rising SYLLABLE_RISE_DB above the
    preceding minimum, at least 100 ms apart, on a 30 ms moving average."""
    if len(band_levels) < 3:
        return 0.0
    smooth = [
        math.fsum(band_levels[max(0, i - 1) : i + 2]) / len(band_levels[max(0, i - 1) : i + 2])
        for i in range(len(band_levels))
    ]
    peaks, low, last_peak = 0, smooth[0], -10
    for i in range(1, len(smooth) - 1):
        low = min(low, smooth[i])
        if (
            smooth[i] >= smooth[i - 1]
            and smooth[i] > smooth[i + 1]
            and smooth[i] - low >= SYLLABLE_RISE_DB
            and i - last_peak >= 10
        ):
            peaks, low, last_peak = peaks + 1, smooth[i], i
    return peaks / (len(band_levels) * HOP_MS / 1000)


def speech_activity(full: list[float], band: list[float], duration_ms: int) -> Iterator[Feature]:
    blocks = []
    for i in range(0, len(full), BLOCK_HOPS):
        total = math.fsum(full[i : i + BLOCK_HOPS])
        speech = math.fsum(band[i : i + BLOCK_HOPS])
        count = len(full[i : i + BLOCK_HOPS])
        ratio = speech / total if total > 0 else 0.0
        blocks.append(level_db(total / count) >= SPEECH_MIN_DBFS and ratio >= SPEECH_BAND_RATIO)
    runs: list[tuple[int, int]] = []
    start = gap = None
    for i, voiced in enumerate([*blocks, False]):
        if voiced:
            start = i if start is None else start
            gap = None
        elif start is not None:
            gap = i if gap is None else gap
            if i - gap >= SPEECH_GAP_BLOCKS or i == len(blocks):
                runs.append((start, gap))
                start = gap = None
    for first, stop in runs:
        if stop - first < SPEECH_MIN_BLOCKS:
            continue
        a, b = first * BLOCK_HOPS, min(len(full), stop * BLOCK_HOPS)
        band_levels = [level_db(e) for e in band[a:b]]
        mean_band = math.fsum(band_levels) / len(band_levels)
        spread = math.fsum((x - mean_band) ** 2 for x in band_levels)
        modulation = math.sqrt(spread / len(band_levels))
        rate = _syllable_rate(band_levels)
        if modulation < SPEECH_MODULATION_DB or not SYLLABLE_MIN_HZ <= rate <= SYLLABLE_MAX_HZ:
            continue  # steady tones, hum and noise are not speech-like
        total, speech = math.fsum(full[a:b]), math.fsum(band[a:b])
        ratio = speech / total if total > 0 else 0.0
        confidence = 0.5 + 0.2 * _clamp((ratio - SPEECH_BAND_RATIO) / 0.35, 0, 1)
        confidence += 0.2 * _clamp((modulation - SPEECH_MODULATION_DB) / 6, 0, 1)
        yield Feature(
            "speech_activity",
            a * HOP_MS,
            min(duration_ms, b * HOP_MS),
            round(min(0.9, confidence), 3),
            round(level_db(total / (b - a)), 2),
            (
                ("band_ratio", round(ratio, 3)),
                ("modulation_db", round(modulation, 2)),
                ("syllable_rate_hz", round(rate, 2)),
            ),
        )


def features(
    audio: AudioSamples, duration_ms: int, check: Callable[[], None] = lambda: None
) -> list[Feature]:
    full = hop_energies(audio.full, audio.sample_rate, check)
    band = hop_energies(audio.speech_band, audio.sample_rate, check)
    band = band[: len(full)]
    full = full[: len(band)]
    duration_ms = min(duration_ms, len(full) * HOP_MS) if full else 0
    if duration_ms <= 0:
        return []
    levels = [level_db(e) for e in full]
    check()
    found = [
        *onsets(levels, duration_ms),
        *silences(envelope(full), duration_ms),
        *speech_activity(full, band, duration_ms),
    ]
    found = [f for f in found if f.end_ms > f.start_ms]
    return sorted(found, key=lambda f: (f.start_ms, f.kind))


EVENT_TYPES = {
    "impact": "openworld.audio_impact",
    "onset": "openworld.audio_onset",
    "silence": "openworld.silence",
    "speech_activity": "openworld.speech_activity",
}


class AudioFeatures:
    """Built-in ``audio-features``: emits supporting audio evidence only."""

    id = "audio-features"
    version = "1.0.0"
    capabilities = frozenset({"audio.pcm"})
    required_regions: frozenset[str] = frozenset()

    def setup(self, context: AnalysisContext) -> None:
        return None

    def detect(self, context: AnalysisContext) -> Iterator[Detection]:
        if context.audio is None:  # no audio stream: nothing to report, not a failure
            return
        found = features(context.audio, context.duration_ms, context.check_cancelled)
        for index, feature in enumerate(found):
            context.check_cancelled()
            context.progress(index + 1, len(found))
            yield Detection(
                EVENT_TYPES[feature.kind],
                feature.start_ms,
                feature.end_ms,
                feature.confidence,
                (
                    {
                        "kind": "audio",
                        "start_ms": feature.start_ms,
                        "end_ms": feature.end_ms,
                        "score": feature.confidence,
                        "feature": feature.kind,
                        "level_dbfs": feature.level_dbfs,
                        "role": "supporting",
                    },
                ),
                {
                    "evidence_role": "supporting",
                    "feature": feature.kind,
                    "level_dbfs": feature.level_dbfs,
                    **dict(feature.details),
                },
            )

    def close(self) -> None:
        return None
