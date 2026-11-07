# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent M19 temporal holdout recipes. Never used to tune a detector."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from openworld_moments.detectors.profiles import canonical
from openworld_moments.evaluation.service import EvaluationError
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import MediaTools


def generate(output: Path, tools: MediaTools) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    recipes = [
        (8000, [(1000, 3000), (4500, 6500)], [(3500, 4000)]),
        (6000, [(2000, 4000)], []),
        (5000, [], [(1500, 2500)]),
    ]
    clips = []
    mapping = {}
    for i, (duration, positive, flicker) in enumerate(recipes):
        raw = output / f"holdout-{i}.gray"
        with raw.open("wb") as stream:
            for at in range(0, duration, 500):
                bright = any(a <= at < b for a, b in positive + flicker)
                stream.write(bytes([255 if bright else 64]) * (320 * 180))
        media = output / f"holdout-{i}.mp4"
        result = run_tool(
            [
                *tools.tool("ffmpeg").command,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-f",
                "rawvideo",
                "-pixel_format",
                "gray",
                "-video_size",
                "320x180",
                "-framerate",
                "2",
                "-i",
                str(raw),
                "-vf",
                "fps=30",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                str(18 + i * 6),
                "-pix_fmt",
                "yuv420p",
                str(media),
            ],
            timeout_s=60,
        )
        raw.unlink(missing_ok=True)
        if result.returncode:
            raise EvaluationError(
                "evaluation.fixture_failed", "Synthetic holdout generation failed."
            )
        sha = hashlib.sha256(media.read_bytes()).hexdigest()
        mapping[sha] = str(media.resolve())
        clips.append(
            {
                "sha256": sha,
                "duration_ms": duration,
                "width": 320,
                "height": 180,
                "locale": "en",
                "hud_scale": 1,
                "compression": "light" if i == 0 else "heavy",
                "annotations": [
                    {"type": "synthetic.bright_region", "start_ms": a, "end_ms": b}
                    for a, b in positive
                ],
            }
        )
    manifest = {
        "schema_version": "1.14",
        "dataset_id": "synthetic-temporal-holdout-v1",
        "split": "holdout",
        "provenance": "synthetic",
        "profile": {"id": "generic-open-world", "version": "1.0.0"},
        "tolerance_ms": 0,
        "clips": clips,
    }
    (output / "manifest.json").write_text(canonical(manifest) + "\n", "utf-8")
    (output / "media-map.private.json").write_text(
        json.dumps(mapping, sort_keys=True) + "\n", "utf-8"
    )
    return manifest
