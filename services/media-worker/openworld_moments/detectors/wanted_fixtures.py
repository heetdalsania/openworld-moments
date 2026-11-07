# SPDX-License-Identifier: AGPL-3.0-or-later
"""Original procedural geometry for replay fixtures. No game-derived templates/media."""

from __future__ import annotations

import math
from collections.abc import Sequence

from openworld_moments.detectors.sdk import Frame

FIXTURE_VERSION = "wanted-synthetic-v1"
DEFAULT_REGION = (0.5, 0.05, 0.45, 0.16)


def polygon(
    pixels: bytearray, width: int, height: int, points: Sequence[tuple[float, float]], value: int
) -> None:
    """Independent scanline rasterizer; the estimator uses a point-in-polygon mask."""
    for row in range(height):
        y = row + 0.5
        crossings = []
        for i, (ax, ay) in enumerate(points):
            bx, by = points[(i + 1) % len(points)]
            if (ay > y) != (by > y):
                crossings.append(ax + (y - ay) * (bx - ax) / (by - ay))
        crossings.sort()
        for a, b in zip(crossings[::2], crossings[1::2], strict=True):
            start = max(0, math.ceil(a - 0.5))
            end = min(width, math.ceil(b - 0.5))
            pixels[row * width + start : row * width + end] = bytes([value]) * max(0, end - start)


def row_pixels(
    width: int,
    height: int,
    level: int,
    *,
    maximum: int = 5,
    shape: str = "star",
    brightness: float = 1,
    pattern: str = "normal",
) -> bytes:
    background = round(20 * brightness)
    pixels = bytearray([background]) * (width * height)
    if pattern == "absent":
        return bytes(pixels)
    for slot in range(maximum):
        x = (slot + 0.5) * width / maximum
        y = height / 2
        radius = min(width / maximum, height) * 0.4

        def vertices(
            scale: float, x: float = x, y: float = y, radius: float = radius
        ) -> list[tuple[float, float]]:
            count = 10 if shape == "star" else 80
            return [
                (
                    x
                    + radius
                    * scale
                    * math.cos(-math.pi / 2 + i * 2 * math.pi / count)
                    * (1 if shape != "star" or i % 2 == 0 else 0.45),
                    y
                    + radius
                    * scale
                    * math.sin(-math.pi / 2 + i * 2 * math.pi / count)
                    * (1 if shape != "star" or i % 2 == 0 else 0.45),
                )
                for i in range(count)
            ]

        if pattern == "rectangles":
            outer = [
                (x - radius, y - radius),
                (x + radius, y - radius),
                (x + radius, y + radius),
                (x - radius, y + radius),
            ]
        else:
            outer = vertices(1)
        on = slot < level
        if pattern == "nonprefix":
            on = slot == maximum - 1
        polygon(pixels, width, height, outer, round((240 if on else 200) * brightness))
        if not on:
            polygon(pixels, width, height, vertices(0.7), background)
        if pattern == "ambiguous":
            polygon(pixels, width, height, vertices(0.5), round(110 * brightness))
    return bytes(pixels)


def fixture_frame(
    level: int,
    source_ms: int = 0,
    *,
    shape: str = "star",
    maximum: int = 5,
    brightness: float = 1,
    pattern: str = "normal",
    region: tuple[float, ...] = DEFAULT_REGION,
) -> Frame:
    return Frame(
        source_ms,
        200,
        40,
        row_pixels(
            200, 40, level, shape=shape, maximum=maximum, brightness=brightness, pattern=pattern
        ),
        region,
    )


def canvas_pixels(
    width: int,
    height: int,
    level: int,
    *,
    region: tuple[float, ...] = DEFAULT_REGION,
    shape: str = "star",
    brightness: float = 1,
) -> bytes:
    x, y, w, h = region
    left, top = int(x * width), int(y * height)
    rw, rh = int(w * width), int(h * height)
    row = row_pixels(rw, rh, level, shape=shape, brightness=brightness)
    # Keep the unrelated picture clear of M08's whole-frame black cutoff (24).
    # The actual indicator ROI retains its dark background and contrast cases.
    canvas = bytearray([round(64 * brightness)]) * (width * height)
    for j in range(rh):
        canvas[(top + j) * width + left : (top + j) * width + left + rw] = row[
            j * rw : (j + 1) * rw
        ]
    return bytes(canvas)
