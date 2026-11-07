# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic timeline coverage hooks. No footage, text, model or network required."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load

from openworld_moments.detectors.profiles import digest
from openworld_moments.stories import algorithm
from openworld_moments.stories.service import StoryRequest

GOLDENS = Path(__file__).resolve().parents[4] / "fixtures/manifests/story-golden-v1.json"


def fixture_snapshot(case: dict[str, Any]) -> tuple[dict[str, Any], StoryRequest]:
    options = {k: case[k] for k in ("pre_roll_ms", "post_roll_ms", "merge_gap_ms") if k in case}
    request = StoryRequest(preset=case.get("preset", "short"), **options)
    events = []
    for i, e in enumerate(case["events"]):
        events.append(
            {
                "event_id": algorithm.stable_id("evt", [case["id"], i]),
                "revision": 0,
                "confidence": 0.95,
                "review_state": "confirmed",
                "source_kind": "detector",
                "supporting": False,
                "spoiler_risk": False,
                **e,
            }
        )
    doc = {
        "session_id": "ses_01JCBQ00000000000000000001",
        "layout_key": digest(case.get("members", case["duration_ms"])),
        "duration_ms": case["duration_ms"],
        "events": events,
        "members": case.get(
            "members",
            [
                {
                    "asset_id": "ast_01JCBQ00000000000000000001",
                    "start_ms": 0,
                    "end_ms": case["duration_ms"],
                    "duration_ms": case["duration_ms"],
                    "hidden_ms": 0,
                }
            ],
        ),
        "speech": [tuple(s) for s in case.get("speech", [])],
        "boundaries": case.get("boundaries", []),
    }
    doc["input_key"] = digest([algorithm.generator(), request.options(), doc])
    return doc, request


def evaluate() -> dict[str, Any]:
    manifest = json.loads(GOLDENS.read_text("utf-8"))
    results = []
    for case in manifest["cases"]:
        snap, request = fixture_snapshot(case)
        docs = algorithm.generate(snap, request.preset, request.options())
        for doc in docs:
            load("story-candidate", doc)
        actual: dict[str, Any] = {"count": len(docs)}
        if docs:
            actual.update(
                {
                    "start_ms": docs[0]["start_ms"],
                    "end_ms": docs[0]["end_ms"],
                    "setup_coverage": docs[0]["metrics"]["setup_coverage"],
                    "payoff_coverage": docs[0]["metrics"]["payoff_coverage"],
                }
            )
        results.append(
            {
                "case": case["id"],
                "passed": actual == case["expected"],
                "expected": case["expected"],
                "actual": actual,
                "speech_truncations": sum(d["metrics"]["speech_truncations"] for d in docs),
                "duplicate_ms": sum(d["metrics"]["duplicate_ms"] for d in docs),
                "score_components": [d["score_components"] for d in docs],
                "warnings": [d["warnings"] for d in docs],
            }
        )
    return {
        "format": "owm-story-coverage-1",
        "generator": algorithm.generator(),
        "provenance": "synthetic",
        "fixture_sha256": digest(manifest),
        "cases": results,
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "manual_boundary_adjustment_ms": None,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Synthetic story coverage",
        "",
        f"Generator: {report['generator']['id']} {report['generator']['version']}.",
        "",
        "| Case | Pass | Setup coverage | Payoff coverage | Speech truncations | Duplicate ms |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in report["cases"]:
        a = row["actual"]
        lines.append(
            f"| {row['case']} | {row['passed']} | {a.get('setup_coverage', 'N/A')} | "
            f"{a.get('payoff_coverage', 'N/A')} | "
            f"{row['speech_truncations']} | {row['duplicate_ms']} |"
        )
    lines.extend(
        [
            "",
            "Setup is measured pre-event context, not a claim of semantic "
            "understanding. Payoff requires an explicit supported event. Audio never "
            "seeds a story.",
            "No gameplay quality, publishing performance or human boundary-adjustment "
            "result is claimed. Median manual boundary adjustment is unmeasured.",
            "",
        ]
    )
    return "\n".join(lines)
