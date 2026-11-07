# SPDX-License-Identifier: AGPL-3.0-or-later
"""Overlap alignment between adjacent clips (spec 8.2.3, M12).

Console replay captures often repeat footage: the start of clip B shows what the end
of clip A already showed. ``align`` looks for B's head inside A's tail using the M06
fingerprints (``dhash256`` frame hashes at 2 fps and ``energy-envelope`` audio at
10 Hz over the first and last 30 s of each clip), and reports where B starts in A.

``owm-overlap`` v1:

1. **Candidates.** Every pair of non-flat frames (A tail, B head) within the match
   distance votes for an offset ``d`` = time in A where B's time 0 falls, in 500 ms
   bins. Offsets that do not put B's start inside A's tail are ignored.
2. **Verification.** For each of the best-voted offsets, B's head frames are walked
   in order and compared with A's frame at the same moment (``t_B + d``). A candidate
   needs at least ``MIN_COMPARED`` compared frames, ``MIN_RATIO`` of them matching,
   and an unbroken run of ``MIN_RUN`` matches. Isolated similar frames fail.
3. **Ambiguity.** If another verified offset (more than one bin away) is nearly as
   well supported, the footage repeats itself (menus, static scenes) and the result
   is ``ambiguous``: never applied.
4. **Refinement.** ``d`` becomes the median offset of the matched frame pairs; with
   audio on both sides, the envelopes are cross-correlated within ±1 s in 100 ms
   steps, and a strong correlation refines ``d`` and raises confidence.

Confidence = matching ratio x min(1, run / ``FULL_RUN``), +``AUDIO_BONUS`` when audio
agrees, at most 0.95. Only ``matched`` results (confidence >= ``APPLY_CONFIDENCE``)
change a session's timeline; everything else leaves both clips whole.

Bump :data:`ALIGN_VERSION` whenever a rule changes: stored results with another
version are stale and recomputed.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

ALIGN_ALGORITHM = "owm-overlap"
ALIGN_VERSION = 1

SAMPLE_MS = 500  # dhash256 sampling interval (2 fps)
ENVELOPE_MS = 100  # energy-envelope interval (10 Hz)
MAX_DISTANCE = 24  # bits of 256, as in M06 perceptual matching
MIN_COMPARED = 4
MIN_RATIO = 0.8
MIN_RUN = 4  # consecutive matching samples (2 s)
FULL_RUN = 8  # a 4 s unbroken match earns full run credit
TOP_CANDIDATES = 5
AMBIGUITY_RATIO = 0.8
AUDIO_SEARCH_MS = 1000
AUDIO_MIN_SAMPLES = 20  # 2 s of envelope
AUDIO_MIN_CORRELATION = 0.7
AUDIO_BONUS = 0.1
MAX_CONFIDENCE = 0.95
APPLY_CONFIDENCE = 0.6

Status = Literal["matched", "weak", "ambiguous", "no_match", "insufficient"]


@dataclass(frozen=True)
class Frame:
    t_ms: int
    value: int  # 256-bit hash as an integer

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Frame | None:
        if raw.get("flat"):
            return None
        return cls(int(raw["t_ms"]), int(raw["hash"], 16))


@dataclass(frozen=True)
class Side:
    """One clip's fingerprint window: frames, and optionally its envelope."""

    duration_ms: int
    frames: tuple[Frame, ...]
    window_start_ms: int
    envelope: tuple[int, ...] = ()
    envelope_start_ms: int = 0

    @classmethod
    def tail(cls, duration_ms: int, frames: dict[str, Any], audio: dict[str, Any] | None) -> Side:
        parsed = tuple(f for f in (Frame.parse(r) for r in frames.get("tail", [])) if f)
        start = min((int(r["t_ms"]) for r in frames.get("tail", [])), default=0)
        env = tuple(audio.get("tail", [])) if audio else ()
        env_start = int(audio.get("tail_start_ms", 0)) if audio else 0
        return cls(duration_ms, parsed, start, env, env_start)

    @classmethod
    def head(cls, duration_ms: int, frames: dict[str, Any], audio: dict[str, Any] | None) -> Side:
        parsed = tuple(f for f in (Frame.parse(r) for r in frames.get("head", [])) if f)
        env = tuple(audio.get("head", [])) if audio else ()
        env_start = int(audio.get("head_start_ms", 0)) if audio else 0
        return cls(duration_ms, parsed, 0, env, env_start)


@dataclass(frozen=True)
class Check:
    offset_ms: int
    compared: int
    matched: int
    longest_run: int
    pairs: tuple[tuple[int, int], ...]  # (t_A, t_B) of matched samples

    @property
    def ratio(self) -> float:
        return self.matched / self.compared if self.compared else 0.0

    @property
    def verified(self) -> bool:
        return (
            self.compared >= MIN_COMPARED
            and self.ratio >= MIN_RATIO
            and self.longest_run >= MIN_RUN
        )


@dataclass(frozen=True)
class Alignment:
    status: Status
    offset_ms: int | None = None
    overlap_ms: int | None = None
    confidence: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def applied(self) -> bool:
        return self.status == "matched"


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _plausible(offset_ms: int, a: Side, b: Side) -> bool:
    """B must start inside A's tail and the overlap must fit in both clips."""
    overlap = a.duration_ms - offset_ms
    return (
        offset_ms >= a.window_start_ms - SAMPLE_MS
        and 0 < overlap <= b.duration_ms + SAMPLE_MS
        and offset_ms > 0
    )


def candidates(a: Side, b: Side) -> Counter[int]:
    """Votes per offset bin (bin x SAMPLE_MS = offset of B's start in A)."""
    votes: Counter[int] = Counter()
    for fa in a.frames:
        for fb in b.frames:
            if _hamming(fa.value, fb.value) <= MAX_DISTANCE:
                offset = fa.t_ms - fb.t_ms
                if _plausible(offset, a, b):
                    votes[round(offset / SAMPLE_MS)] += 1
    return votes


def verify(a: Side, b: Side, offset_ms: int) -> Check:
    """Walk B's head along ``offset_ms`` and compare with A's frame at the same moment."""
    by_time = {f.t_ms: f for f in a.frames}
    a_times = sorted(by_time)
    compared = matched = run = longest = 0
    pairs: list[tuple[int, int]] = []
    for fb in b.frames:
        target = fb.t_ms + offset_ms
        if target >= a.duration_ms or target < a.window_start_ms - SAMPLE_MS // 2:
            continue
        nearest = min(a_times, key=lambda t: abs(t - target), default=None)
        if nearest is None or abs(nearest - target) > SAMPLE_MS // 2:
            continue
        compared += 1
        if _hamming(by_time[nearest].value, fb.value) <= MAX_DISTANCE:
            matched += 1
            run += 1
            longest = max(longest, run)
            pairs.append((nearest, fb.t_ms))
        else:
            run = 0
    return Check(offset_ms, compared, matched, longest, tuple(pairs))


def _audio_refine(a: Side, b: Side, offset_ms: int, overlap_ms: int) -> tuple[int, float] | None:
    """Best lag within ±AUDIO_SEARCH_MS by envelope correlation, if strong enough."""
    if len(a.envelope) < AUDIO_MIN_SAMPLES or len(b.envelope) < AUDIO_MIN_SAMPLES:
        return None
    best: tuple[int, float] | None = None
    for lag in range(offset_ms - AUDIO_SEARCH_MS, offset_ms + AUDIO_SEARCH_MS + 1, ENVELOPE_MS):
        xs: list[int] = []
        ys: list[int] = []
        for k, value in enumerate(b.envelope):
            t_b = b.envelope_start_ms + k * ENVELOPE_MS
            if t_b >= overlap_ms:
                break
            index = (t_b + lag - a.envelope_start_ms) / ENVELOPE_MS
            i = round(index)
            if 0 <= i < len(a.envelope):
                xs.append(a.envelope[i])
                ys.append(value)
        if len(xs) < AUDIO_MIN_SAMPLES:
            continue
        corr = _pearson(xs, ys)
        if corr is not None and (best is None or corr > best[1]):
            best = (lag, corr)
    if best is None or best[1] < AUDIO_MIN_CORRELATION:
        return None
    return best


def _pearson(xs: Sequence[int], ys: Sequence[int]) -> float | None:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / math.sqrt(sxx * syy)


def align(a: Side, b: Side) -> Alignment:
    """Where clip B (following A) starts inside A, if B repeats A's ending."""
    base: dict[str, Any] = {
        "a_frames": len(a.frames),
        "b_frames": len(b.frames),
        "max_distance": MAX_DISTANCE,
    }
    if len(a.frames) < MIN_COMPARED or len(b.frames) < MIN_COMPARED:
        return Alignment("insufficient", evidence={**base, "reason": "too_few_frames"})
    votes = candidates(a, b)
    if not votes:
        return Alignment("no_match", evidence={**base, "candidates": 0})
    ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_CANDIDATES]
    checks = [verify(a, b, bin_ * SAMPLE_MS) for bin_, _ in ranked]
    verified = [c for c in checks if c.verified]
    evidence = {
        **base,
        "candidates": len(votes),
        "top_votes": [{"offset_ms": bin_ * SAMPLE_MS, "votes": n} for bin_, n in ranked],
    }
    if not verified:
        best_try = max(checks, key=lambda c: (c.matched, c.ratio))
        return Alignment(
            "no_match",
            evidence={**evidence, **_check_doc(best_try), "reason": "no_continuous_match"},
        )
    best = max(verified, key=lambda c: (c.matched, c.ratio, -abs(c.offset_ms)))
    rivals = [
        c
        for c in verified
        if abs(c.offset_ms - best.offset_ms) > SAMPLE_MS
        and c.matched >= AMBIGUITY_RATIO * best.matched
    ]
    if rivals:
        return Alignment(
            "ambiguous",
            evidence={
                **evidence,
                **_check_doc(best),
                "rival_offsets_ms": sorted(c.offset_ms for c in rivals),
                "reason": "repeating_footage",
            },
        )
    offset = round(statistics.median(ta - tb for ta, tb in best.pairs))
    overlap = max(0, min(a.duration_ms - offset, b.duration_ms))
    confidence = best.ratio * min(1.0, best.longest_run / FULL_RUN)
    audio = _audio_refine(a, b, offset, overlap)
    details = {**evidence, **_check_doc(best), "visual_offset_ms": offset}
    if audio is not None:
        offset = audio[0]
        overlap = max(0, min(a.duration_ms - offset, b.duration_ms))
        confidence += AUDIO_BONUS
        details["audio_correlation"] = round(audio[1], 4)
        details["audio_offset_ms"] = audio[0]
    confidence = round(min(MAX_CONFIDENCE, confidence), 3)
    status: Status = "matched" if confidence >= APPLY_CONFIDENCE else "weak"
    return Alignment(status, offset, overlap, confidence, details)


def _check_doc(check: Check) -> dict[str, Any]:
    return {
        "compared_frames": check.compared,
        "matching_frames": check.matched,
        "longest_run": check.longest_run,
    }
