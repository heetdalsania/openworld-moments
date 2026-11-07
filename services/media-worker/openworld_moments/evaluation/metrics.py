# SPDX-License-Identifier: AGPL-3.0-or-later
"""Maximum-cardinality one-to-one interval matching with inclusive boundary tolerance."""

from __future__ import annotations

from collections.abc import Callable
from statistics import median
from typing import Any


def match(
    expected: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    tolerance: int,
    check: Callable[[], None] = lambda: None,
) -> list[tuple[int, int]]:
    # Stable ordering and edge preference are part of owm-eval-1. Augmenting
    # paths maximize TP count; a greedy nearest-neighbour pass can undercount.
    order = sorted(
        range(len(observed)),
        key=lambda i: (observed[i]["type"], observed[i]["start_ms"], observed[i]["end_ms"], i),
    )
    edges = {}
    for i in order:
        check()
        p = observed[i]
        edges[i] = sorted(
            (
                j
                for j, a in enumerate(expected)
                if a["type"] == p["type"]
                and abs(a["start_ms"] - p["start_ms"]) <= tolerance
                and abs(a["end_ms"] - p["end_ms"]) <= tolerance
            ),
            key=lambda j: (
                abs(expected[j]["start_ms"] - p["start_ms"])
                + abs(expected[j]["end_ms"] - p["end_ms"]),
                j,
            ),
        )
    assigned: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        check()
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in assigned or augment(assigned[j], seen):
                assigned[j] = i
                return True
        return False

    for i in order:
        augment(i, set())
    return sorted((j, i) for j, i in assigned.items())


def measure(
    clips: list[dict[str, Any]], tolerance: int, check: Callable[[], None] = lambda: None
) -> dict[str, Any]:
    tp = fp = fn = duration = 0
    processing = 0.0
    errors: list[float] = []
    for clip in clips:
        check()
        a, p = clip["annotations"], clip["events"]
        pairs = match(a, p, tolerance, check)
        tp += len(pairs)
        fp += len(p) - len(pairs)
        fn += len(a) - len(pairs)
        duration += clip["duration_ms"]
        processing += clip["processing_ms"]
        errors.extend(
            (abs(a[j]["start_ms"] - p[i]["start_ms"]) + abs(a[j]["end_ms"] - p[i]["end_ms"])) / 2
            for j, i in pairs
        )
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "false_positives_per_hour": fp * 3_600_000 / duration if duration else None,
        "median_timestamp_error_ms": median(errors) if errors else None,
        "duration_ms": duration,
        "processing_ms": round(processing, 6),
        "realtime_factor": duration / processing if processing else None,
    }
