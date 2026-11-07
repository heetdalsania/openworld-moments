# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scratch-only synthetic lettering via OpenCV's licensed Hershey renderer.

OpenCV/NumPy are development dependencies; runtime detectors do not import them.
No font file, screenshot or generated media is redistributed in this repository.
"""

from __future__ import annotations

from openworld_moments.detectors.sdk import Frame

FIXTURE_VERSION = "text-synthetic-v1"
BANNER_REGION = (0.1, 0.2, 0.8, 0.24)
SUBTITLE_REGION = (0.1, 0.72, 0.8, 0.24)


def pixels(
    text: str,
    width: int = 640,
    height: int = 128,
    *,
    scale: float = 1.1,
    brightness: float = 1,
    outline: bool = False,
    contrast: int = 220,
    style: str = "simplex",
) -> bytes:
    import cv2
    import numpy as np

    font = cv2.FONT_HERSHEY_SIMPLEX if style == "simplex" else cv2.FONT_HERSHEY_DUPLEX
    image = np.full((height, width), round(20 * brightness), dtype=np.uint8)
    thickness = max(1, round(2 * width / 640))
    lines = text.split("\n") if text else []
    longest = max((cv2.getTextSize(s, font, scale, thickness)[0][0] for s in lines), default=1)
    scale *= min(1, (width - 40) / max(1, longest))
    line_height = cv2.getTextSize("Ag", font, scale, thickness)[0][1]
    step = line_height + round(18 * scale)
    top = (height - max(1, len(lines)) * step) // 2 + line_height
    for index, line in enumerate(lines):
        line_width = cv2.getTextSize(line, font, scale, thickness)[0][0]
        point = ((width - line_width) // 2, top + index * step)
        if outline:
            cv2.putText(image, line, point, font, scale, 0, thickness * 3, cv2.LINE_AA)
        cv2.putText(
            image,
            line,
            point,
            font,
            scale,
            round(min(255, 20 + contrast) * brightness),
            thickness,
            cv2.LINE_AA,
        )
    return bytes(image.tobytes())


def frame(
    text: str,
    at: int = 0,
    *,
    region: tuple[float, ...] = BANNER_REGION,
    scale: float = 1.1,
    brightness: float = 1,
    outline: bool = False,
    contrast: int = 220,
    style: str = "simplex",
) -> Frame:
    return Frame(
        at,
        640,
        128,
        pixels(
            text,
            scale=scale,
            brightness=brightness,
            outline=outline,
            contrast=contrast,
            style=style,
        ),
        region,
    )


def canvas(
    width: int,
    height: int,
    banner: str,
    subtitle: str = "",
    *,
    brightness: float = 1,
    outline: bool = False,
    banner_region: tuple[float, ...] = BANNER_REGION,
    subtitle_region: tuple[float, ...] = SUBTITLE_REGION,
) -> bytes:
    image = bytearray([round(64 * brightness)]) * (width * height)
    for text, region in ((banner, banner_region), (subtitle, subtitle_region)):
        x, y, w, h = region
        left, top, rw, rh = int(x * width), int(y * height), int(w * width), int(h * height)
        picture = pixels(text, rw, rh, scale=1.1 * rw / 640, brightness=brightness, outline=outline)
        for row in range(rh):
            image[(top + row) * width + left : (top + row) * width + left + rw] = picture[
                row * rw : (row + 1) * rw
            ]
    return bytes(image)
