# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conservative analytic indicator-row estimator and temporal wanted-state filter.

Templates are mathematical stars/discs, not extracted or official game artwork.
A visible inactive outline is required in every unfilled slot, including state zero.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from statistics import median
from types import MappingProxyType
from typing import Any

from openworld_moments.detectors.sdk import AnalysisContext, AnalysisError, Detection, Frame

VERSION = "1.0.0"
REGION = "wanted_indicator"
SAMPLE_MS = 500


def inside(x: float, y: float, shape: str) -> bool:
    """Unit-radius analytic silhouette. The star has five outer and five inner vertices."""
    if shape == "disc":
        return x * x + y * y <= 1
    vertices = tuple(
        (
            math.cos(-math.pi / 2 + i * math.pi / 5) * (1 if i % 2 == 0 else 0.45),
            math.sin(-math.pi / 2 + i * math.pi / 5) * (1 if i % 2 == 0 else 0.45),
        )
        for i in range(10)
    )
    result = False
    for i, (ax, ay) in enumerate(vertices):
        bx, by = vertices[(i + 1) % 10]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
    return result


@dataclass(frozen=True)
class SlotMask:
    all: tuple[int, ...]
    outer: frozenset[int]
    ring: frozenset[int]
    core: tuple[int, ...]
    background: tuple[int, ...]


@lru_cache(maxsize=16)
def masks(width: int, height: int, maximum: int, shape: str) -> tuple[SlotMask, ...]:
    output = []
    slot_width = width / maximum
    radius = min(slot_width, height) * 0.4
    for slot in range(maximum):
        all_pixels = []
        outer = set()
        ring = set()
        core = []
        background = []
        for row in range(height):
            for col in range(int(slot * slot_width), int((slot + 1) * slot_width)):
                index = row * width + col
                x = (col + 0.5 - (slot + 0.5) * slot_width) / radius
                y = (row + 0.5 - height / 2) / radius
                all_pixels.append(index)
                if inside(x, y, shape):
                    outer.add(index)
                    if not inside(x / 0.7, y / 0.7, shape):
                        ring.add(index)
                else:
                    background.append(index)
                if inside(x / 0.5, y / 0.5, shape):
                    core.append(index)
        output.append(
            SlotMask(
                tuple(all_pixels), frozenset(outer), frozenset(ring), tuple(core), tuple(background)
            )
        )
    return tuple(output)


@dataclass(frozen=True)
class Observation:
    level: int | None
    confidence: float
    reason: str
    slot_scores: tuple[float, ...] = ()


def estimate(frame: Frame, maximum: int = 5, shape: str = "star") -> Observation:
    if maximum not in range(1, 11) or shape not in ("star", "disc"):
        raise AnalysisError("wanted.invalid_settings", "Unsupported indicator geometry.")
    if (
        frame.width < maximum * 12
        or frame.height < 12
        or frame.width * frame.height > 8000
        or len(frame.pixels) != frame.width * frame.height
    ):
        raise AnalysisError(
            "wanted.invalid_sample", "A bounded, sufficiently detailed ROI is required."
        )
    active = []
    scores = []
    for mask in masks(frame.width, frame.height, maximum, shape):
        background = float(median(frame.pixels[i] for i in mask.background))
        rim = float(median(frame.pixels[i] for i in mask.ring))
        core = float(median(frame.pixels[i] for i in mask.core))
        contrast = rim - background
        if contrast < 30 or rim < 50:
            return Observation(None, 0, "outline_missing_or_low_contrast")
        fill = (core - background) / contrast
        if fill >= 0.75:
            on = True
            expected = mask.outer
        elif fill <= 0.25:
            on = False
            expected = mask.ring
        else:
            return Observation(None, 0.5, "ambiguous_fill")
        observed = {i for i in mask.all if frame.pixels[i] >= background + 0.5 * contrast}
        dice = 2 * len(observed & expected) / max(1, len(observed) + len(expected))
        if dice < 0.78:
            return Observation(None, min(0.77, dice), "shape_mismatch")
        score = 0.6 * dice + 0.25 * min(1, abs(fill - 0.5) * 2) + 0.15 * min(1, contrast / 60)
        active.append(on)
        scores.append(score)
    count = sum(active)
    if active != [True] * count + [False] * (maximum - count):
        return Observation(None, 0, "noncontiguous_indicators", tuple(scores))
    return Observation(count, min(scores), "observed", tuple(scores))


@dataclass(frozen=True)
class Transition:
    previous: int
    level: int
    first_ms: int
    confirmed_ms: int
    confidence: float
    frames: int
    temporal_score: float


class TemporalState:
    def __init__(
        self, confirmation: int = 3, missing: int = 1, debounce: int = 1500, minimum: float = 0.8
    ) -> None:
        if (
            type(confirmation) is not int
            or not 1 <= confirmation <= 600
            or type(missing) is not int
            or not 0 <= missing <= 20
            or type(debounce) is not int
            or not 0 <= debounce <= 30000
            or not math.isfinite(minimum)
            or not 0 <= minimum <= 1
        ):
            raise AnalysisError(
                "wanted.invalid_settings", "Invalid temporal confirmation settings."
            )
        self.confirmation, self.allowed_missing, self.debounce, self.minimum = (
            confirmation,
            missing,
            debounce,
            minimum,
        )
        self.stable: int | None = None
        self.candidate: int | None = None
        self.hits: deque[tuple[int, float]] = deque(maxlen=confirmation)
        self.misses = 0
        self.miss_times: deque[int] = deque(maxlen=confirmation * (missing + 1))
        self.last_ms: int | None = None
        self.last_event: int | None = None

    def clear_candidate(self) -> None:
        self.candidate = None
        self.hits.clear()
        self.miss_times.clear()

    def observe(self, time_ms: int, observation: Observation) -> Transition | None:
        if self.last_ms is not None:
            if time_ms <= self.last_ms:
                raise AnalysisError("wanted.invalid_sample", "Sample times must strictly ascend.")
            if time_ms - self.last_ms > 750:
                self.stable = None
                self.clear_candidate()
                self.misses = 0
        self.last_ms = time_ms
        if observation.level is None or observation.confidence < self.minimum:
            self.misses += 1
            self.miss_times.append(time_ms)
            if self.misses > self.allowed_missing:
                self.stable = None
                self.clear_candidate()
            return None
        self.misses = 0
        if observation.level == self.stable:
            self.clear_candidate()
            return None
        if observation.level != self.candidate:
            self.clear_candidate()
            self.candidate = observation.level
        self.hits.append((time_ms, observation.confidence))
        while self.miss_times and self.miss_times[0] < self.hits[0][0]:
            self.miss_times.popleft()
        if len(self.hits) < self.confirmation:
            return None
        if self.stable is None:
            self.stable = observation.level
            self.clear_candidate()
            return None
        if self.last_event is not None and time_ms - self.last_event < self.debounce:
            return None
        temporal = len(self.hits) / (len(self.hits) + len(self.miss_times))
        confidence = min(score for _, score in self.hits) * (
            1 - 0.05 * len(self.miss_times) / max(1, len(self.hits))
        )
        if confidence < self.minimum:
            return None
        transition = Transition(
            self.stable,
            observation.level,
            self.hits[0][0],
            time_ms,
            confidence,
            len(self.hits),
            temporal,
        )
        self.stable = observation.level
        self.last_event = time_ms
        self.clear_candidate()
        return transition


class WantedState:
    id = "wanted-indicators"
    version = VERSION
    capabilities = frozenset({"frames.gray"})
    required_regions = frozenset({REGION})
    sample_region = REGION  # Fixed source registry permission, never a profile filter string.

    def setup(self, context: AnalysisContext) -> None:
        pass

    def close(self) -> None:
        pass

    def replay(self, context: AnalysisContext) -> Iterator[tuple[dict[str, Any], Detection | None]]:
        settings = context.settings.get("wanted", {})
        maximum = settings.get("max_level", 5)
        shape = settings.get("shape", "star")
        temporal = TemporalState(
            context.settings.get("confirmation_frames", 3),
            settings.get("max_missing_frames", 1),
            settings.get("debounce_ms", 1500),
            context.settings.get("min_confidence", 0.8),
        )
        region = context.regions[REGION]
        for index, frame in enumerate(context.frames):
            context.check_cancelled()
            if frame.region != region or not 0 <= frame.source_ms < context.duration_ms:
                raise AnalysisError(
                    "wanted.invalid_sample", "Wanted inputs must name the calibrated ROI."
                )
            observation = estimate(frame, maximum, shape)
            change = temporal.observe(frame.source_ms, observation)
            detection = None
            if change:
                detection = Detection(
                    "openworld.wanted_level_changed",
                    change.first_ms,
                    min(context.duration_ms, change.confirmed_ms + SAMPLE_MS),
                    change.confidence,
                    (
                        MappingProxyType(
                            {
                                "kind": "region_template",
                                "region": region,
                                "frame_ms": frame.source_ms,
                                "score": observation.confidence,
                            }
                        ),
                        MappingProxyType(
                            {
                                "kind": "temporal_consistency",
                                "frames": change.frames,
                                "score": change.temporal_score,
                            }
                        ),
                    ),
                    MappingProxyType(
                        {
                            "from": change.previous,
                            "to": change.level,
                            "max_level": maximum,
                            "direction": "escalation"
                            if change.level > change.previous
                            else "de-escalation",
                            "confirmed_at_ms": change.confirmed_ms,
                            "compatibility": "unvalidated",
                        }
                    ),
                )
            trace = {
                "source_ms": frame.source_ms,
                "observed": observation.level,
                "confidence": observation.confidence,
                "reason": observation.reason,
                "stable": temporal.stable,
                "candidate": temporal.candidate,
                "hits": len(temporal.hits),
                "misses": temporal.misses,
                "slot_scores": list(observation.slot_scores),
                "transition": dict(detection.attributes) if detection else None,
            }
            context.progress(index + 1, max(1, len(context.frames)))
            yield trace, detection

    def detect(self, context: AnalysisContext) -> Iterable[Detection]:
        for _, finding in self.replay(context):
            if finding is not None:
                yield finding
