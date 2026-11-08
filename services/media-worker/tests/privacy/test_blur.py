# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from openworld_moments.privacy.blur import expression, pixels, region_at

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/synthetic/privacy-blur-v1.json"


def test_shared_geometry_goldens() -> None:
    data = json.loads(FIXTURE.read_text())
    for case in data["cases"]:
        region = region_at(data["blur"], case["at_ms"])
        assert region == pytest.approx(case["region"])
        assert pixels(region, case["width"], case["height"]) == case["pixels"]
    assert region_at(data["blur"], 0) == data["blur"]["region"]
    assert region_at(data["blur"], 3000) == data["blur"]["keyframes"][-1]["region"]
    assert "floor(" in expression(data["blur"], 0, 1280, 256)
