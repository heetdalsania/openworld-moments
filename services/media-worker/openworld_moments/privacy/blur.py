# SPDX-License-Identifier: AGPL-3.0-or-later
"""Output-normalized fixed-size linear blur translation, shared with preview goldens."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any


def region_at(blur: dict[str, Any], at_ms: float) -> list[float]:
    keys = blur.get("keyframes") or [{"at_ms": 0, "region": blur["region"]}]
    local = max(0, at_ms - blur["start_ms"])
    for left, right in pairwise(keys):
        if local <= right["at_ms"]:
            f = max(0.0, min(1.0, (local - left["at_ms"]) / (right["at_ms"] - left["at_ms"])))
            return [
                left["region"][i] + (right["region"][i] - left["region"][i]) * f for i in range(4)
            ]
    return list(keys[-1]["region"])


def pixels(region: list[float], width: int, height: int) -> list[int]:
    x, y, w, h = region
    # Floor dimensions/positions to chroma-aligned coordinates. Round half up in both runtimes.
    pw, ph = (
        min(width, max(8, math.floor(w * width / 2 + 0.5) * 2)),
        min(height, max(8, math.floor(h * height / 2 + 0.5) * 2)),
    )
    return [
        min(width - pw, math.floor(x * width / 2 + 1e-9) * 2),
        min(height - ph, math.floor(y * height / 2 + 1e-9) * 2),
        pw,
        ph,
    ]


def expression(blur: dict[str, Any], axis: int, size: int, extent: int) -> str:
    keys = blur.get("keyframes") or [{"at_ms": 0, "region": blur["region"]}]
    result = f"{keys[-1]['region'][axis]:.12f}"
    for left, right in reversed(list(pairwise(keys))):
        a, b = (blur["start_ms"] + left["at_ms"]) / 1000, (blur["start_ms"] + right["at_ms"]) / 1000
        x, delta = left["region"][axis], right["region"][axis] - left["region"][axis]
        result = (
            f"if(lt(t,{b:.3f}),{x:.12f}+{delta:.12f}*clip((t-{a:.3f})/{b - a:.3f},0,1),{result})"
        )
    return f"min({size - extent},floor(({result})*{size}/2+0.000000001)*2)"
