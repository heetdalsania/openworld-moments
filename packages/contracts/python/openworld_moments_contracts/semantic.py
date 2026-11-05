# SPDX-License-Identifier: Apache-2.0
"""Rules JSON Schema cannot express. Mirrors src/semantic.ts; shared fixtures keep them aligned."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from itertools import pairwise
from typing import Any

_EPSILON = 1e-9

Document = dict[str, Any]


def _region(path: str, region: list[float]) -> Iterable[str]:
    x, y, w, h = region
    if x + w > 1 + _EPSILON:
        yield f"{path}: region extends past the right edge (x + width = {x + w:g} > 1)"
    if y + h > 1 + _EPSILON:
        yield f"{path}: region extends past the bottom edge (y + height = {y + h:g} > 1)"


def _range(path: str, start: int, end: int, *, strict: bool = False) -> Iterable[str]:
    if end < start or (strict and end == start):
        relation = "greater than" if strict else "at least"
        yield f"{path}: end ({end}) must be {relation} start ({start})"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(doc: Document) -> Iterable[str]:
    yield from _range("end_ms", doc["start_ms"], doc["end_ms"])
    if doc["source"]["kind"] == "detector" and not doc["evidence"]:
        yield "evidence: detector observations need at least one piece of evidence"
    for i, item in enumerate(doc["evidence"]):
        yield from _evidence(f"evidence[{i}]", item)


def _evidence(path: str, item: Document) -> Iterable[str]:
    if "region" in item:
        yield from _region(f"{path}.region", item["region"])
    if "start_ms" in item:
        yield from _range(f"{path}.end_ms", item["start_ms"], item["end_ms"])


def _job(doc: Document) -> Iterable[str]:
    progress = doc.get("progress")
    if progress and progress["done"] > progress["total"]:
        yield f"progress: done ({progress['done']}) exceeds total ({progress['total']})"
    if doc["state"] == "failed" and "error" not in doc:
        yield "error: failed jobs must include an error"
    order = [k for k in ("created_at", "started_at", "finished_at") if k in doc]
    for earlier, later in pairwise(order):
        if _parse_time(doc[later]) < _parse_time(doc[earlier]):
            yield f"{later}: must not be before {earlier}"


def _profile(doc: Document) -> Iterable[str]:
    for name, region in doc["regions"].items():
        yield from _region(f"regions.{name}", region)
    for name in doc.get("safe_zones", {}).get("preserve", []):
        if name not in doc["regions"]:
            yield f"safe_zones.preserve: '{name}' is not defined in regions"


def _project(doc: Document) -> Iterable[str]:
    for t, track in enumerate(doc["tracks"]):
        for s, seg in enumerate(track["segments"]):
            path = f"tracks[{t}].segments[{s}]"
            yield from _range(
                f"{path}.source_out_ms", seg["source_in_ms"], seg["source_out_ms"], strict=True
            )
            for k, frame in enumerate(seg["crop"]["keyframes"]):
                yield from _region(f"{path}.crop.keyframes[{k}].region", frame["region"])
    for i, caption in enumerate(doc["captions"]):
        yield from _range(
            f"captions[{i}].end_ms", caption["start_ms"], caption["end_ms"], strict=True
        )
    for i, overlay in enumerate(doc["overlays"]):
        yield from _range(
            f"overlays[{i}].end_ms", overlay["start_ms"], overlay["end_ms"], strict=True
        )
        yield from _region(f"overlays[{i}].region", overlay["region"])
    for i, mute in enumerate(doc["audio"]["mute_ranges"]):
        yield from _range(
            f"audio.mute_ranges[{i}].end_ms", mute["start_ms"], mute["end_ms"], strict=True
        )


def _render_preset(doc: Document) -> Iterable[str]:
    video = doc["video"]
    if ("crf" in video) == ("bitrate_kbps" in video):
        yield "video: set exactly one of 'crf' or 'bitrate_kbps'"


def _export_manifest(doc: Document) -> Iterable[str]:
    count = len(doc["sources"])
    for i, seg in enumerate(doc["segments"]):
        if seg["source"] >= count:
            yield f"segments[{i}].source: index {seg['source']} is out of range ({count} sources)"
        yield from _range(f"segments[{i}].out_ms", seg["in_ms"], seg["out_ms"], strict=True)


RULES: dict[str, Callable[[Document], Iterable[str]]] = {
    "event": _event,
    "job": _job,
    "profile": _profile,
    "project": _project,
    "render-preset": _render_preset,
    "export-manifest": _export_manifest,
}


def semantic_issues(contract: str, document: Document) -> list[str]:
    """Return human-readable semantic problems. Assumes the document passed schema validation."""
    rule = RULES.get(contract)
    return list(rule(document)) if rule else []
