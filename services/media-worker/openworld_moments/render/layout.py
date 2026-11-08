# SPDX-License-Identifier: AGPL-3.0-or-later
"""M25 geometry v1. Upright source coordinates, fixed-size smoothstep translation.

Pure numeric planner; profile text never enters a filter expression. Suggestions are
static and explicit in the editor. No face/object tracking or media inference.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

FIT: dict[str, Any] = {
    "layout_version": 1,
    "strategy": "fit",
    "background": "solid",
    "keyframes": [],
}


def region_at(layout: dict[str, Any], ms: float) -> list[float]:
    keys = layout["keyframes"]
    if not keys or layout["strategy"] == "fit":
        return [0, 0, 1, 1]
    for a, b in pairwise(keys):
        if ms < b["at_ms"]:
            q = max(0.0, min(1.0, (ms - a["at_ms"]) / (b["at_ms"] - a["at_ms"])))
            q = q * q * (3 - 2 * q)
            return [a["region"][i] + (b["region"][i] - a["region"][i]) * q for i in range(4)]
    return list(keys[-1]["region"])


def pixels(region: list[float], width: int, height: int) -> list[int]:
    if region == [0, 0, 1, 1]:
        return [0, 0, width, height]
    x, y, w, h = region
    cw = min(width, max(2, math.floor(w * width / 2 + 1e-9) * 2))
    ch = min(height, max(2, math.floor(h * height / 2 + 1e-9) * 2))
    return [
        min(width - cw, max(0, math.floor(x * width + 1e-9))),
        min(height - ch, max(0, math.floor(y * height + 1e-9))),
        cw,
        ch,
    ]


def fit_rect(width: int, height: int, out_w: int = 1080, out_h: int = 1920) -> list[int]:
    scale = min(out_w / width, out_h / height)
    w = max(2, math.floor(width * scale / 2 + 1e-9) * 2)
    h = max(2, math.floor(height * scale / 2 + 1e-9) * 2)
    return [(out_w - w) // 2, (out_h - h) // 2, w, h]


def visible_fraction(region: list[float], zone: list[float]) -> float:
    x, y, w, h = region
    a, b, c, d = zone
    return max(0, min(x + w, a + c) - max(x, a)) * max(0, min(y + h, b + d) - max(y, b)) / (c * d)


def warnings(
    layout: dict[str, Any],
    width: int,
    height: int,
    profile: dict[str, Any] | None,
    overlays: list[dict[str, Any]] | None = None,
) -> list[str]:
    if profile:
        frame = profile["frame"]
        ratios = [list(map(int, r.split(":"))) for r in frame["aspect_ratios"]]
        if (
            width < frame["min_width"]
            or height < frame["min_height"]
            or not any(abs(width / height - a / b) / (a / b) <= 0.01 for a, b in ratios)
        ):
            profile = None
    if not profile:
        return ["No compatible current profile: protected HUD regions are unknown."]
    names = profile.get("safe_zones", {}).get("preserve", [])
    if not names:
        return ["The profile declares no protected HUD regions."]
    times = [k["at_ms"] for k in layout["keyframes"]] or [0]
    times += [(a + b) / 2 for a, b in pairwise(times)]
    result = []
    for name in names:
        zone = profile["regions"][name]
        mapped_boxes = []
        for ms in times:
            px, py, cw, ch = pixels(region_at(layout, ms), width, height)
            crop = [px / width, py / height, cw / width, ch / height]
            if visible_fraction(crop, zone) < 0.95 - 1e-9:
                result.append(f"Protected region {name}: more than 5% is removed by the crop.")
                break
            ox, oy, fw, fh = fit_rect(cw, ch)
            zx, zy, zw, zh = zone
            mapped = [
                (ox + (zx * width - px) * fw / cw) / 1080,
                (oy + (zy * height - py) * fh / ch) / 1920,
                zw * width * fw / cw / 1080,
                zh * height * fh / ch / 1920,
            ]
            mapped_boxes.append(mapped)
        else:
            # A blur can cross a moving HUD between sampled times. Use its swept
            # envelope conservatively; never miss a narrow crossing between keys.
            left = min(r[0] for r in mapped_boxes)
            top = min(r[1] for r in mapped_boxes)
            right = max(r[0] + r[2] for r in mapped_boxes)
            bottom = max(r[1] + r[3] for r in mapped_boxes)
            swept = [left, top, right - left, bottom - top]
            area = min(r[2] * r[3] for r in mapped_boxes)
            if any(
                visible_fraction(o["region"], swept) * swept[2] * swept[3] / area > 0.05
                for o in overlays or []
            ):
                result.append(f"Protected region {name}: a privacy blur may obscure it.")
    return result


def position_expression(layout: dict[str, Any], axis: int, size: int) -> str:
    """Only validated numeric literals. Crop evaluates x/y per source frame."""
    keys = layout["keyframes"]
    expression = f"{keys[-1]['region'][axis] * size:.12f}"
    for a, b in reversed(list(pairwise(keys))):
        start, end = a["at_ms"] / 1000, b["at_ms"] / 1000
        q = f"clip((t-{start:.6f})/{end - start:.6f},0,1)"
        base = a["region"][axis] * size
        delta = (b["region"][axis] - a["region"][axis]) * size
        value = f"{base:.12f}+({delta:.12f})*({q})*({q})*(3-2*({q}))"
        expression = f"if(lt(t,{end:.6f}),{value},{expression})"
    return f"floor({expression}+0.000000001)"
