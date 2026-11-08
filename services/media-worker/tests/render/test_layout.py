# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent expected geometry, shared with the preview; conservative warnings."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.render.encoders import CPU
from openworld_moments.render.layout import FIT, fit_rect, pixels, region_at, warnings
from openworld_moments.render.plan import RenderError, SourceFacts, build_plan
from openworld_moments.render.presets import PresetCatalog
from tests.render.test_plan import A, document, segment

GOLDENS = json.loads(
    (Path(__file__).resolve().parents[4] / "fixtures/synthetic/vertical-layout-v1.json").read_text()
)["cases"]
PROFILE = {
    "frame": {"min_width": 1, "min_height": 1, "aspect_ratios": ["16:9"]},
    "regions": {"left": [0, 0.8, 0.2, 0.2], "right": [0.8, 0, 0.2, 0.2]},
    "safe_zones": {"preserve": ["left", "right"]},
}


@pytest.mark.parametrize("case", GOLDENS, ids=lambda c: c["name"])
def test_shared_golden(case: dict[str, Any]) -> None:
    r = pixels(region_at(case["layout"], case["at_ms"]), *case["size"])
    assert r == case["pixels"]
    assert fit_rect(*r[2:]) == case["fit"]


def test_protected_regions_and_unknown_profile() -> None:
    assert warnings(FIT, 1920, 1080, PROFILE) == []
    v = {**FIT, "strategy": "fixed", "keyframes": [{"at_ms": 0, "region": [0.3, 0, 0.3, 1]}]}
    assert len(warnings(v, 1920, 1080, PROFILE)) == 2
    assert "unknown" in warnings(v, 1920, 1080, None)[0]
    assert "unknown" in warnings(v, 1080, 1920, PROFILE)[0]
    assert warnings(FIT, 1920, 1080, PROFILE, [{"region": [0, 0.58, 0.3, 0.09]}])


def test_vertical_plan_is_independent_and_requires_explicit_review() -> None:
    doc = document(segment(1, A, 0, 0, 2000, mode="fill"))
    before = copy.deepcopy(doc)
    facts = {A: SourceFacts(A, "a" * 64, "clip.mp4", False, (30, 1), None, 640, 360)}
    preset = PresetCatalog().get("vertical-1080x1920-30")
    with pytest.raises(RenderError, match="Review vertical"):
        build_plan(doc, facts, preset, CPU, ffmpeg_version="7.1")
    plan = build_plan(doc, facts, preset, CPU, ffmpeg_version="7.1", review_layout=True)
    assert doc == before
    assert plan["output"]["width"] == 1080 and plan["output"]["height"] == 1920
    assert plan["segments"][0]["vertical_crop"] == FIT
    assert "scale=1080:606" in plan["command"]["filter_complex"]


def test_keyed_plan_uses_continuous_expressions_and_one_input_per_cut() -> None:
    doc = document(segment(1, A, 0, 0, 2000))
    v = GOLDENS[-1]["layout"]
    doc["project"]["tracks"][0]["segments"][0]["vertical_crop"] = v
    facts = {A: SourceFacts(A, "a" * 64, "clip.mp4", False, (30, 1), None, 640, 360)}
    plan = build_plan(
        doc,
        facts,
        PresetCatalog().get("vertical-source-fps"),
        CPU,
        ffmpeg_version="7.1",
        review_layout=True,
    )
    assert len(plan["segments"]) == 1
    assert "if(lt(t,1.000000)" in plan["command"]["filter_complex"]
    assert plan["segments"][0]["frames"] == 60


def test_narrow_privacy_blur_crossing_between_keys_warns() -> None:
    profile = {
        "frame": {"min_width": 1, "min_height": 1, "aspect_ratios": ["16:9"]},
        "regions": {"hud": [0.5, 0.1, 0.01, 0.02]},
        "safe_zones": {"preserve": ["hud"]},
    }
    layout = {
        **FIT,
        "strategy": "keyed",
        "keyframes": [
            {"at_ms": 0, "region": [0, 0, 0.8, 1]},
            {"at_ms": 1000, "region": [0.2, 0, 0.8, 1]},
        ],
    }
    assert warnings(layout, 1920, 1080, profile, [{"region": [0.56, 0.34, 0.02, 0.02]}]) == [
        "Protected region hud: a privacy blur may obscure it."
    ]


def test_many_hud_warnings_and_hdr_still_produce_a_valid_bounded_record() -> None:
    from openworld_moments.derived.tonemap import ToneMapSettings
    from openworld_moments.detectors.profiles import ProfileCatalog
    from tests.render.test_plan import record

    profile = ProfileCatalog().load("generic-text").document()
    names = [f"hud-{i}" for i in range(40)]
    profile["regions"].update({name: [0, 0, 0.1, 0.1] for name in names})
    profile["safe_zones"] = {"preserve": names}
    doc = document(segment(1, A, 0, 0, 2000))
    doc["project"]["tracks"][0]["segments"][0]["vertical_crop"] = {
        **FIT,
        "strategy": "fixed",
        "keyframes": [{"at_ms": 0, "region": [0.3, 0, 0.3, 1]}],
    }
    facts = {
        A: SourceFacts(
            A, "a" * 64, "clip.mp4", False, (30, 1), ToneMapSettings("smpte2084"), 640, 360
        )
    }
    plan = build_plan(
        doc,
        facts,
        PresetCatalog().get("vertical-1080x1920-30"),
        CPU,
        ffmpeg_version="7.1",
        review_layout=True,
        layout_profile=profile,
    )
    record(plan)
    assert len(plan["notes"]) == 20
    assert "further notices" in plan["notes"][-1]
