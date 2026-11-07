# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uncached real-OCR benchmark on generated development fixtures, never user footage."""

from __future__ import annotations

import platform
import statistics
import threading
import time
from typing import Any

from openworld_moments.detectors.inputs import OCR_SAMPLER_VERSION
from openworld_moments.detectors.ocr import Tesseract
from openworld_moments.detectors.sdk import SDK_VERSION, AnalysisError
from openworld_moments.detectors.text import classify, normalize
from openworld_moments.detectors.text_fixtures import FIXTURE_VERSION, frame


def benchmark(samples: int = 60, repeats: int = 3) -> dict[str, Any]:
    if not 12 <= samples <= 60 or not 1 <= repeats <= 3:
        raise AnalysisError("ocr.invalid_benchmark", "Use 12-60 samples and 1-3 repetitions.")
    try:
        import cv2
    except ImportError as exc:
        raise AnalysisError(
            "ocr.fixtures_unavailable",
            "Install the development dependencies to generate benchmark fixtures.",
        ) from exc
    backend = Tesseract()
    versions = backend.prepare("eng", threading.Event())
    vocabulary = {
        "failure": ("TRY AGAIN",),
        "arrest": ("CAUGHT",),
        "mission-started": ("TASK STARTED",),
        "mission-objective": ("NEW OBJECTIVE",),
        "mission-completed": ("TASK COMPLETE",),
        "mission-failed": ("TASK FAILED",),
    }
    cases = [(phrases[0], category) for category, phrases in vocabulary.items()] + [
        ("BLUE UMBRELLA", None)
    ]
    fixtures = [frame(text) for text, _ in cases]
    subtitle_text = "MORGAN: MEET AT BRIDGE\nBRING THE BLUE CASE"
    subtitle = frame(subtitle_text)
    elapsed = []
    exact = correct = 0
    for _ in range(repeats):
        exact = correct = 0
        start = time.perf_counter()
        for index in range(samples):
            reading = backend.read(fixtures[index % len(fixtures)], "contrast", threading.Event())
            text, category = cases[index % len(cases)]
            exact += normalize(reading.text) == normalize(text)
            found, _ = classify(reading.text, vocabulary, 0.9)
            correct += found == category and reading.score >= 0.75
            dialogue = backend.read(subtitle, "threshold", threading.Event())
            exact += normalize(dialogue.text) == normalize(subtitle_text)
        backend.verify_model(threading.Event())
        elapsed.append(time.perf_counter() - start)
    wall = statistics.median(elapsed)
    return {
        "fixture_version": FIXTURE_VERSION,
        "renderer": "opencv-hershey-" + cv2.__version__,
        "sdk_version": SDK_VERSION,
        "sampler_version": OCR_SAMPLER_VERSION,
        "tool_versions": versions,
        "hardware": {
            "machine": platform.machine(),
            "system": platform.system(),
            "python": platform.python_version(),
        },
        "samples": samples,
        "ocr_calls": samples * 2,
        "repeats": repeats,
        "input_seconds": samples / 2,
        "wall_seconds": elapsed,
        "median_seconds": wall,
        "realtime_factor": samples / 2 / wall,
        "budget_2x_met": samples / 2 / wall >= 2,
        "exact_text": exact,
        "correct_categories": correct,
        "includes": (
            "uncached banner and subtitle OCR, preprocessing and matching; "
            "excludes proxy/decode/I/O"
        ),
        "compatibility": "synthetic only; game compatibility unvalidated",
    }
