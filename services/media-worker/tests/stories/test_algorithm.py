# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import copy
import json
from itertools import pairwise
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.detectors.profiles import canonical
from openworld_moments.stories import algorithm
from openworld_moments.stories.golden import GOLDENS, evaluate, fixture_snapshot, markdown

CASES = json.loads(GOLDENS.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_golden_timeline(case: dict[str, Any]) -> None:
    snap, request = fixture_snapshot(case)
    docs = algorithm.generate(snap, request.preset, request.options())
    assert canonical(docs) == canonical(
        algorithm.generate(copy.deepcopy(snap), request.preset, request.options())
    )
    actual = {"count": len(docs)}
    if docs:
        actual.update(
            {
                "start_ms": docs[0]["start_ms"],
                "end_ms": docs[0]["end_ms"],
                "setup_coverage": docs[0]["metrics"]["setup_coverage"],
                "payoff_coverage": docs[0]["metrics"]["payoff_coverage"],
            }
        )
    assert actual == case["expected"]
    for doc in docs:
        load("story-candidate", doc)
        assert (
            sum(r["source_out_ms"] - r["source_in_ms"] for r in doc["source_ranges"])
            == doc["end_ms"] - doc["start_ms"]
        )
        assert abs(doc["score"] - sum(doc["score_components"].values())) < 0.0000011
    assert all(a["end_ms"] <= b["start_ms"] for a, b in pairwise(docs))


def test_review_threshold_and_supporting_audio_never_seed_even_relabelled() -> None:
    snap, request = fixture_snapshot(CASES[0])
    e = snap["events"][0]
    e.update(review_state="unreviewed", confidence=0.899999)
    assert not algorithm.generate(snap, request.preset, request.options())
    e["confidence"] = 0.9
    assert algorithm.generate(snap, request.preset, request.options())
    assert not algorithm.generate(
        snap, request.preset, {**request.options(), "allow_unreviewed": False}
    )
    e.update(review_state="confirmed", source_kind="model", confidence=0.1)
    assert algorithm.generate(snap, request.preset, request.options())
    e["review_state"] = "unreviewed"
    e["confidence"] = 1
    assert not algorithm.generate(snap, request.preset, request.options())
    e.update(review_state="corrected", supporting=True)
    assert not algorithm.generate(snap, request.preset, request.options())
    e.update(supporting=False, review_state="rejected")
    assert not algorithm.generate(snap, request.preset, request.options())


@pytest.mark.parametrize("preset", tuple(algorithm.PRESETS))
def test_presets_hard_max_speech_pressure_and_available_short_session(preset: str) -> None:
    case = copy.deepcopy(CASES[0])
    case["preset"] = preset
    snap, request = fixture_snapshot(case)
    maximum = algorithm.PRESETS[preset][1]
    snap["duration_ms"] = 300000
    snap["members"][0].update(end_ms=300000, duration_ms=300000)
    snap["speech"] = [(0, maximum + 1000)]
    doc = algorithm.generate(snap, preset, request.options())[0]
    assert doc["end_ms"] - doc["start_ms"] <= maximum
    assert "speech_truncated" in doc["warnings"]
    snap["speech"] = []
    snap["duration_ms"] = 3000
    snap["members"][0].update(end_ms=3000, duration_ms=3000)
    snap["events"][0].update(start_ms=500, end_ms=2500)
    doc = algorithm.generate(snap, preset, request.options())[0]
    assert (doc["start_ms"], doc["end_ms"]) == (0, 3000)
    assert "below_minimum" in doc["warnings"]


def test_score_penalties_alternatives_and_cancellation() -> None:
    snap, request = fixture_snapshot(CASES[0])
    snap["events"][0]["spoiler_risk"] = True
    rejected = {
        **snap["events"][0],
        "event_id": algorithm.stable_id("evt", "rejected"),
        "review_state": "rejected",
    }
    snap["events"].append(rejected)
    doc = algorithm.generate(snap, request.preset, {**request.options(), "avoid_spoilers": True})[0]
    assert doc["score_components"]["spoiler_risk_penalty"] == -0.1
    assert doc["score_components"]["rejection_penalty"] == -0.2
    assert doc["alternatives"]
    for alternative in doc["alternatives"]:
        assert alternative["end_ms"] - alternative["start_ms"] <= 60000
    checks = 0

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise InterruptedError

    with pytest.raises(InterruptedError):
        algorithm.generate(snap, request.preset, request.options(), cancel)


def test_explicit_scene_and_silence_outward_boundaries_and_report_privacy() -> None:
    snap, request = fixture_snapshot(CASES[0])
    snap["boundaries"] = [6000, 34000]
    doc = algorithm.generate(snap, request.preset, request.options())[0]
    assert (doc["start_ms"], doc["end_ms"]) == (6000, 34000)
    report = evaluate()
    assert report["passed"] == report["total"] == 10
    assert "Setup coverage" in markdown(report)
    assert report["manual_boundary_adjustment_ms"] is None
    assert not any(
        x in canonical(report) for x in ("private_path", "transcript_text", "OCR_SECRET")
    )


def test_causal_join_requires_related_types_and_input_order_is_irrelevant() -> None:
    snap, request = fixture_snapshot(CASES[0])
    options = {**request.options(), "pre_roll_ms": 0, "post_roll_ms": 0, "merge_gap_ms": 30000}
    e = {
        **snap["events"][0],
        "type": "openworld.wanted_level_changed",
        "from": 0,
        "to": 2,
        "start_ms": 10000,
        "end_ms": 11000,
    }
    other = {
        **e,
        "event_id": algorithm.stable_id("evt", "second"),
        "start_ms": 40000,
        "end_ms": 41000,
        "from": 2,
        "to": 0,
    }
    snap["events"] = [other, e]
    doc = algorithm.generate(snap, "short", options)
    assert len(doc) == 1
    assert {b["kind"] for b in doc[0]["beats"]} == {"incident", "payoff"}
    snap["events"] = [e, other]
    assert doc == algorithm.generate(snap, "short", options)
    other["type"] = "openworld.manual"
    assert len(algorithm.generate(snap, "short", options)) == 2


def test_candidate_resource_budget_fails_before_unbounded_output() -> None:
    snap, request = fixture_snapshot(CASES[0])
    original = snap["events"][0]
    snap["duration_ms"] = 200000000
    snap["members"][0].update(end_ms=200000000, duration_ms=200000000)
    snap["events"] = [
        {
            **original,
            "event_id": algorithm.stable_id("evt", i),
            "start_ms": i * 100000,
            "end_ms": i * 100000 + 1000,
        }
        for i in range(1001)
    ]
    with pytest.raises(algorithm.StoryLimitError):
        algorithm.generate(snap, "short", request.options())
