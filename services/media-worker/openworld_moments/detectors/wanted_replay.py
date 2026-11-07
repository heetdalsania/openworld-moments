# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local wanted replay/benchmark reports. Image bytes are separate, optional PGM crops."""

from __future__ import annotations

import contextlib
import json
import platform
import statistics
import threading
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any

from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.inputs import (
    ROI_SAMPLER_VERSION,
    decode_region,
    require_roi_detail,
)
from openworld_moments.detectors.profiles import ProfileCatalog, compatibility
from openworld_moments.detectors.sdk import SDK_VERSION, AnalysisContext, AnalysisError, Frame
from openworld_moments.detectors.service import Analyzer
from openworld_moments.detectors.wanted import REGION, WantedState
from openworld_moments.detectors.wanted_fixtures import FIXTURE_VERSION, fixture_frame
from openworld_moments.ids import new_id
from openworld_moments.media.tools import MediaTools
from openworld_moments.storage import AssetRepository, Database


def replay(
    asset_id: str,
    library: Path,
    profile_id: str,
    catalog: ProfileCatalog,
    output: Path,
    *,
    crops: bool = False,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise AnalysisError(
            "wanted.output_exists", "Choose a new report directory; existing files are preserved."
        )
    if not (library / "database.sqlite3").is_file():
        raise AnalysisError("wanted.library_missing", "Choose an existing imported library.")
    database = Database.open(library / "database.sqlite3")
    tools = MediaTools()
    analyzer = Analyzer(database, tools, DerivedMedia(database, tools), catalog=catalog)
    resolved = analyzer.profile(profile_id)
    profile = resolved.document()
    setting = next(
        (s for s in profile["detectors"] if s["id"] == WantedState.id and s["enabled"]), None
    )
    if setting is None or REGION not in profile["regions"]:
        raise AnalysisError(
            "wanted.profile_incompatible", "The profile needs an enabled wanted detector and ROI."
        )
    cancel = cancel or threading.Event()
    from openworld_moments.detectors.sdk import checkpoint

    started = time.perf_counter()
    with contextlib.closing(database.connect()) as conn:
        asset = AssetRepository(conn).get(asset_id)
        if asset.video is None:
            raise AnalysisError("wanted.no_video", "A video asset is required.")
        width, height = asset.video.width, asset.video.height
        if asset.video.rotation in (90, 270):
            width, height = height, width
        compatibility(profile, width, height, None)
        require_roi_detail(
            width,
            height,
            tuple(profile["regions"][REGION]),
            setting.get("wanted", {}).get("max_level", 5),
        )
        path, input_key, versions = analyzer._prepare(conn, asset_id, new_id("job"), cancel)
    region = tuple(profile["regions"][REGION])
    frames = decode_region(path, tools.tool("ffmpeg"), cancel, region)
    versions["sampler"] = ROI_SAMPLER_VERSION
    context = AnalysisContext(
        asset_id,
        asset.duration_ms,
        frames,
        MappingProxyType({REGION: region}),
        MappingProxyType(setting),
        MappingProxyType({}),
        lambda: checkpoint(cancel),
        lambda *_: None,
    )
    rows: list[dict[str, Any]] = []
    events = []
    crop_frames = {}
    detector = WantedState()
    try:
        detector.setup(context)
        for row, event in detector.replay(context):
            if event is not None:
                events.append(
                    {
                        "type": event.type,
                        "start_ms": event.start_ms,
                        "end_ms": event.end_ms,
                        "confidence": event.confidence,
                        "attributes": dict(event.attributes),
                        "evidence": [dict(e) for e in event.evidence],
                    }
                )
                if crops:
                    name = f"crops/{row['source_ms']:012d}.pgm"
                    row["crop_ref"] = name
                    crop_frames[name] = frames[len(rows)]
            rows.append(row)
    finally:
        detector.close()
    checkpoint(cancel)
    report = {
        "format": "owm-wanted-replay",
        "version": 1,
        "complete": True,
        "asset_id": asset_id,
        "profile_id": profile_id,
        "profile_key": resolved.key,
        "input_key": input_key,
        "tool_versions": versions,
        "detector_version": detector.version,
        "compatibility": "unvalidated",
        "samples": len(rows),
        "events": events,
        "wall_seconds": time.perf_counter() - started,
    }
    output.mkdir(parents=True, exist_ok=False)
    if crop_frames:
        (output / "crops").mkdir()
    for name, frame in crop_frames.items():
        with (output / name).open("xb") as stream:
            stream.write(f"P5\n{frame.width} {frame.height}\n255\n".encode() + frame.pixels)
    with (output / "trace.jsonl").open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
    return report


def benchmark(seconds: int = 3600, repeats: int = 5) -> dict[str, Any]:
    if not 10 <= seconds <= 3600 or not 1 <= repeats <= 5:
        raise AnalysisError("wanted.invalid_benchmark", "Use 10-3600 seconds and 1-5 repeats.")
    pixels = {level: fixture_frame(level).pixels for level in (0, 2, 5)}
    region = fixture_frame(0).region
    frames = tuple(
        Frame(i * 500, 200, 40, pixels[(0, 2, 5, 0)[i // 6 % 4]], region)
        for i in range(seconds * 2)
    )
    context = AnalysisContext(
        "synthetic-benchmark",
        seconds * 1000,
        frames,
        MappingProxyType({REGION: region or ()}),
        MappingProxyType({}),
        MappingProxyType({}),
        lambda: None,
        lambda *_: None,
    )
    elapsed = []
    count = 0
    for _ in range(repeats):
        started = time.perf_counter()
        count = len(list(WantedState().detect(context)))
        elapsed.append(time.perf_counter() - started)
    wall = statistics.median(elapsed)
    return {
        "fixture_version": FIXTURE_VERSION,
        "detector_version": WantedState.version,
        "sdk_version": SDK_VERSION,
        "sampler_version": ROI_SAMPLER_VERSION,
        "hardware": {
            "machine": platform.machine(),
            "processor": platform.processor(),
            "system": platform.system(),
            "python": platform.python_version(),
        },
        "input_seconds": seconds,
        "frames": len(frames),
        "repeats": repeats,
        "events": count,
        "wall_seconds": elapsed,
        "median_seconds": wall,
        "realtime_factor": seconds / wall,
        "budget_2x_met": seconds / wall >= 2,
        "includes": "estimator and temporal filter; excludes decode/proxy/I/O",
        "compatibility": "synthetic only; game compatibility unvalidated",
    }
