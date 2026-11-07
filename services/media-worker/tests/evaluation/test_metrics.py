# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import copy
import threading
from typing import Any

import pytest

from openworld_moments.detectors.profiles import canonical, digest
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.evaluation.metrics import match, measure
from openworld_moments.evaluation.service import EvaluationError, evaluate, markdown


def interval(a: int, b: int, kind: str = "openworld.test") -> dict[str, Any]:
    return {"type": kind, "start_ms": a, "end_ms": b}


def sample() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = {
        "schema_version": "1.14",
        "dataset_id": "test-holdout",
        "split": "holdout",
        "provenance": "synthetic",
        "profile": {"id": "generic-open-world", "version": "1.0.0"},
        "tolerance_ms": 100,
        "clips": [
            {
                "sha256": "a" * 64,
                "duration_ms": 3600000,
                "width": 1280,
                "height": 720,
                "locale": "en",
                "hud_scale": 1,
                "compression": "heavy",
                "annotations": [interval(1000, 2000), interval(5000, 6000)],
            }
        ],
    }
    observed = {
        "schema_version": "1.14",
        "manifest_sha256": digest(manifest),
        "profile": manifest["profile"],
        "detectors": [{"id": "synthetic-bright-region", "version": "1.0.0"}],
        "clips": [
            {
                "sha256": "a" * 64,
                "processing_ms": 1000,
                "events": [interval(1100, 2100), interval(10000, 11000)],
            }
        ],
    }
    return manifest, observed


def test_exact_tolerance_wrong_types_duplicates_and_maximum_matching() -> None:
    a = [interval(100, 200), interval(110, 210)]
    p = [interval(100, 200), interval(105, 195)]
    assert set(match(a, p, 10)) == {(0, 1), (1, 0)}  # nearest greedy pairing can lose a TP
    assert match([interval(100, 200)], [interval(110, 210)], 10) == [(0, 0)]
    assert not match([interval(100, 200)], [interval(111, 210)], 10)
    assert not match([interval(100, 200)], [interval(100, 200, "other.type")], 0)
    assert len(match([interval(100, 200)], [interval(100, 200)] * 2, 0)) == 1
    m = measure(
        [
            {
                "annotations": [interval(1, 2)],
                "events": [interval(1, 2)] * 2,
                "duration_ms": 3600000,
                "processing_ms": 0,
            }
        ],
        0,
    )
    assert m["false_positives_per_hour"] == 1 and m["precision"] == 0.5


def test_deterministic_metrics_privacy_and_compatibility_report() -> None:
    manifest, observed = sample()
    report = evaluate(manifest, observed)
    assert report["metrics"] == {
        "true_positives": 1,
        "false_positives": 1,
        "false_negatives": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
        "false_positives_per_hour": 1,
        "median_timestamp_error_ms": 100,
        "duration_ms": 3600000,
        "processing_ms": 1000,
        "realtime_factor": 3600,
    }
    assert canonical(report) == canonical(evaluate(manifest, observed))
    assert markdown(report) == markdown(evaluate(manifest, observed))
    assert report["compatibility"][0]["status"] == "synthetic-only"
    assert "Footage hours" in markdown(report)
    for forbidden in ("source_path", "/Users/", "transcript", "OCR_SECRET"):
        assert forbidden not in canonical(report)
    leaked = copy.deepcopy(observed)
    leaked["clips"][0]["transcript"] = "OCR_SECRET"
    with pytest.raises(EvaluationError, match="invalid"):
        evaluate(manifest, leaked)
    absent = copy.deepcopy(observed)
    absent["clips"] = []
    with pytest.raises(EvaluationError):
        evaluate(manifest, absent)
    changed = copy.deepcopy(manifest)
    changed["tolerance_ms"] = 1
    with pytest.raises(EvaluationError, match="match"):
        evaluate(changed, observed)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AnalysisCancelled):
        evaluate(manifest, observed, cancel)


@pytest.mark.parametrize(
    "a,p,precision,recall,f1", [(0, 0, None, None, None), (1, 0, None, 0, 0), (0, 1, 0, None, 0)]
)
def test_empty_denominators(a: int, p: int, precision: Any, recall: Any, f1: Any) -> None:
    m = measure(
        [
            {
                "annotations": [interval(0, 1)] * a,
                "events": [interval(100, 101)] * p,
                "duration_ms": 1000,
                "processing_ms": 0,
            }
        ],
        0,
    )
    assert (m["precision"], m["recall"], m["f1"]) == (precision, recall, f1)
    assert m["median_timestamp_error_ms"] is None and m["realtime_factor"] is None
