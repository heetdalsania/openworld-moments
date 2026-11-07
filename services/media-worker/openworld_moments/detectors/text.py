# SPDX-License-Identifier: AGPL-3.0-or-later
"""Constrained banner classification and confirmed OCR appearance/disappearance intervals."""

from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from types import MappingProxyType
from typing import Any

from openworld_moments.detectors.inputs import OCR_SIZE
from openworld_moments.detectors.ocr import OcrBackend, Reading, Tesseract
from openworld_moments.detectors.sdk import AnalysisContext, AnalysisError, Detection

CATEGORIES = {
    "failure": "openworld.failure",
    "arrest": "openworld.arrest",
    "mission-started": "openworld.mission_started",
    "mission-objective": "openworld.mission_objective",
    "mission-completed": "openworld.mission_completed",
    "mission-failed": "openworld.mission_failed",
}


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def classify(
    text: str, vocabulary: Mapping[str, tuple[str, ...]], threshold: float
) -> tuple[str | None, float]:
    """Whole text only; ambiguous categories and short fuzzy matches remain unknown."""
    value = normalize(text)
    if not value or len(value) > 200:
        return None, 0
    scores = []
    for category in CATEGORIES:
        best = 0.0
        for phrase in vocabulary.get(category, ()):
            target = normalize(phrase)
            if not target:
                continue
            score = (
                similarity(value, target)
                if min(len(value), len(target)) >= 8
                else float(value == target)
            )
            best = max(best, score)
        scores.append((best, category))
    scores.sort(reverse=True)
    best, category = scores[0]
    if best < threshold or best - scores[1][0] < 0.08:
        return None, best
    return category, best


@dataclass(frozen=True)
class TextSample:
    reading: Reading
    kind: str
    category: str | None
    match: float
    confidence: float
    frame_ms: int
    canonical_text: str | None = None

    @property
    def key(self) -> str:
        return normalize(self.canonical_text or self.reading.text)


@dataclass
class Span:
    sample: TextSample
    first_ms: int
    last_ms: int
    confirmed_ms: int
    hits: int
    minimum: float


class TextIntervals:
    def __init__(self, confirmation: int, missing: int) -> None:
        self.confirmation, self.missing = confirmation, missing
        self.active: Span | None = None
        self.candidate: Span | None = None
        self.absent = 0
        self.last_ms: int | None = None

    @staticmethod
    def same(span: Span, sample: TextSample) -> bool:
        same_text = span.sample.key == sample.key
        if span.sample.canonical_text is None and sample.canonical_text is None:
            same_text |= similarity(span.sample.key, sample.key) >= 0.94
        return (
            span.sample.kind == sample.kind
            and span.sample.category == sample.category
            and same_text
        )

    @staticmethod
    def extend(span: Span, sample: TextSample, at: int) -> None:
        span.last_ms = at
        span.hits += 1
        span.minimum = min(span.minimum, sample.confidence)
        if sample.reading.score > span.sample.reading.score:
            span.sample = sample

    def finish(self, reason: str) -> tuple[Span, str] | None:
        old, self.active = self.active, None
        return (old, reason) if old else None

    def observe(self, at: int, sample: TextSample | None) -> list[tuple[Span, str]]:
        closed = []
        if self.last_ms is not None:
            if at <= self.last_ms:
                raise AnalysisError(
                    "ocr.invalid_sample", "OCR sample timestamps must strictly ascend."
                )
            if at - self.last_ms > 750:
                if event := self.finish("gap"):
                    closed.append(event)
                self.candidate, self.absent = None, 0
        self.last_ms = at
        if sample is None:
            self.absent += 1
            if self.absent > self.missing:
                if event := self.finish("absence"):
                    closed.append(event)
                self.candidate = None
            return closed
        self.absent = 0
        if self.active and self.same(self.active, sample):
            self.extend(self.active, sample, at)
            self.candidate = None
            return closed
        if self.candidate and self.same(self.candidate, sample):
            self.extend(self.candidate, sample, at)
        else:
            self.candidate = Span(sample, at, at, at, 1, sample.confidence)
        if self.candidate.hits >= self.confirmation:
            if event := self.finish("text_changed"):
                closed.append(event)
            self.active, self.candidate = self.candidate, None
            self.active.confirmed_ms = at
        return closed


class TextDetector:
    version = "1.0.0"
    capabilities = frozenset({"frames.gray"})
    sample_dimensions = OCR_SIZE
    id = "region-banner-ocr"
    sample_region = "mission_banner"
    required_regions = frozenset({"mission_banner"})
    subtitle = False

    def __init__(self, backend: OcrBackend | None = None) -> None:
        self.backend = backend or Tesseract()
        self.cancel = threading.Event()
        self.ready = False

    def configure(
        self, setting: Mapping[str, Any], locale: Mapping[str, Any], cancel: threading.Event
    ) -> dict[str, str]:
        language = locale.get("ocr_language")
        if not language:
            raise AnalysisError(
                "profile.incompatible", "locales.ocr_language: an OCR locale pack is required"
            )
        self.cancel = cancel
        versions = self.backend.prepare(language, cancel)
        self.ready = True
        return {**versions, "ocr_locale_version": locale["version"]}

    def setup(self, context: AnalysisContext) -> None:
        if not self.ready:
            raise AnalysisError(
                "ocr.unavailable", "Configure the local OCR adapter before analysis."
            )

    def close(self) -> None:
        if isinstance(self.backend, Tesseract) and self.ready:
            self.backend.verify_model(self.cancel)

    def sample(self, reading: Reading, context: AnalysisContext, at: int) -> TextSample | None:
        settings = context.settings.get("ocr", {})
        if not reading.text or reading.score < settings.get("min_text_confidence", 0.6):
            return None
        if self.subtitle:
            return TextSample(reading, "openworld.subtitle", None, 1, reading.score, at)
        category, score = classify(
            reading.text, context.vocabulary, settings.get("match_threshold", 0.9)
        )
        if category and reading.score >= 0.75:
            phrase = max(
                context.vocabulary[category],
                key=lambda p: similarity(normalize(reading.text), normalize(p)),
            )
            return TextSample(
                reading,
                CATEGORIES[category],
                category,
                score,
                min(reading.score, score),
                at,
                phrase,
            )
        return TextSample(reading, "openworld.ocr_text", None, score, min(0.49, reading.score), at)

    def event(self, span: Span, reason: str, context: AnalysisContext) -> Detection:
        sample = span.sample
        attrs: dict[str, Any] = {
            "text": sample.reading.text,
            "confirmed_at_ms": span.confirmed_ms,
            "last_seen_ms": span.last_ms,
            "closed_by": reason,
            "compatibility": "unvalidated",
        }
        if sample.category:
            attrs.update(category=sample.category, vocabulary_score=sample.match)
            if sample.category.startswith("mission-"):
                attrs.update(spoiler_risk=True, spoiler_reason="mission_text")
        if self.subtitle and (speaker := re.match(r"^([\w][\w ]{0,31}):\s+", sample.reading.text)):
            attrs["speaker"] = speaker[1]
        region = context.regions[self.sample_region]
        elapsed_samples = (span.last_ms - span.first_ms) // 500 + 1
        evidence = (
            MappingProxyType(
                {
                    "kind": "ocr",
                    "region": region,
                    "text": sample.reading.text,
                    "score": sample.reading.score,
                    "frame_ms": sample.frame_ms,
                    "lines": tuple(
                        MappingProxyType(
                            {"text": line.text, "region": line.region, "score": line.score}
                        )
                        for line in sample.reading.lines
                    ),
                }
            ),
            MappingProxyType(
                {
                    "kind": "temporal_consistency",
                    "frames": span.hits,
                    "score": min(1, span.hits / max(1, elapsed_samples)),
                }
            ),
        )
        return Detection(
            sample.kind,
            span.first_ms,
            min(context.duration_ms, span.last_ms + 500),
            span.minimum,
            evidence,
            MappingProxyType(attrs),
        )

    def detect(self, context: AnalysisContext) -> Iterable[Detection]:
        settings = context.settings.get("ocr", {})
        state = TextIntervals(
            context.settings.get("confirmation_frames", 2), settings.get("max_missing_frames", 1)
        )
        mode = settings.get("preprocess", "threshold" if self.subtitle else "contrast")
        cache: OrderedDict[bytes, Reading] = OrderedDict()
        for index, frame in enumerate(context.frames):
            context.check_cancelled()
            if (
                frame.region != context.regions[self.sample_region]
                or not 0 <= frame.source_ms < context.duration_ms
            ):
                raise AnalysisError(
                    "ocr.invalid_sample", "OCR inputs must name the calibrated source region."
                )
            key = hashlib.sha256(frame.pixels).digest()
            reading = cache.get(key)
            if reading is None:
                reading = self.backend.read(frame, mode, self.cancel)
                cache[key] = reading
                if len(cache) > 8:
                    cache.popitem(last=False)
            else:
                cache.move_to_end(key)
            for span, reason in state.observe(
                frame.source_ms, self.sample(reading, context, frame.source_ms)
            ):
                context.check_cancelled()
                yield self.event(span, reason, context)
            context.progress(index + 1, max(1, len(context.frames)))
        if final := state.finish("clip_end"):
            context.check_cancelled()
            yield self.event(*final, context)


class SubtitleDetector(TextDetector):
    id = "region-subtitle-ocr"
    sample_region = "subtitle"
    required_regions = frozenset({"subtitle"})
    subtitle = True
