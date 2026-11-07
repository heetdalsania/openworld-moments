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


def _job_event(doc: Document) -> Iterable[str]:
    for issue in _job(doc["job"]):
        yield f"job.{issue}"


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


_WITH_ASSET = frozenset({"imported", "existing", "relinked"})


def _import(doc: Document) -> Iterable[str]:
    counts = dict.fromkeys(("imported", "existing", "relinked", "skipped", "failed"), 0)
    for i, item in enumerate(doc["items"]):
        outcome = item["outcome"]
        counts[outcome] += 1
        if outcome in _WITH_ASSET:
            if "asset_id" not in item:
                yield f"items[{i}].asset_id: '{outcome}' items must name their asset"
            if "error" in item:
                yield f"items[{i}].error: '{outcome}' items must not carry an error"
        else:
            if "error" not in item:
                yield f"items[{i}].error: '{outcome}' items must explain why"
            if "asset_id" in item:
                yield f"items[{i}].asset_id: '{outcome}' items must not name an asset"
            if "candidate_asset_ids" in item:
                yield f"items[{i}].candidate_asset_ids: '{outcome}' items have no candidates"
    totals = doc["totals"]
    if totals["files"] != len(doc["items"]):
        yield f"totals.files: {totals['files']} does not match {len(doc['items'])} items"
    for outcome, count in counts.items():
        if totals[outcome] != count:
            yield f"totals.{outcome}: {totals[outcome]} does not match {count} items"


def _watched_folder(doc: Document) -> Iterable[str]:
    stats = doc["stats"]
    counted = stats["imported"] + stats["in_progress"] + stats["failed"]
    if counted > stats["tracked"]:
        yield f"stats.tracked: {stats['tracked']} is less than the {counted} files counted by state"


_KINDS = ("proxy", "filmstrip", "waveform")
_COMPLETE = ("ready", "stale", "missing")
_COMPLETE_FIELDS = ("cache_key", "path", "size_bytes", "sha256", "created_at", "recipe")


def _derived_media(doc: Document) -> Iterable[str]:
    decision = doc["proxy_decision"]
    real = [r for r in decision["reasons"] if r["code"] != "no_video"]
    if decision["needed"] != bool(real):
        yield "proxy_decision.needed: must be true exactly when there is a reason"
    kinds = [a["kind"] for a in doc["artifacts"]]
    if kinds != list(_KINDS):
        yield f"artifacts: kinds must be {', '.join(_KINDS)} in that order, got {', '.join(kinds)}"
    for i, art in enumerate(doc["artifacts"]):
        kind, status = art["kind"], art["status"]
        others = [k for k in _KINDS if k != kind and k in art]
        if others:
            yield f"artifacts[{i}]: a {kind} artifact cannot carry {', '.join(others)} info"
        if status in _COMPLETE:
            for field in (*_COMPLETE_FIELDS, kind):
                if field not in art:
                    yield f"artifacts[{i}].{field}: required when status is '{status}'"
            if "path" in art and not art["path"].split("/")[-1].startswith(f"{kind}-"):
                yield f"artifacts[{i}].path: does not name a {kind} artifact"
        else:
            for field in ("path", "size_bytes", "sha256", "created_at", kind):
                if field in art:
                    yield f"artifacts[{i}].{field}: not allowed when status is '{status}'"
        if status == "failed" and "last_error" not in art:
            yield f"artifacts[{i}].last_error: required when status is 'failed'"
        info = art.get(kind)
        if kind == "filmstrip" and info is not None:
            times = info["times_ms"]
            if info["count"] != len(times):
                yield f"artifacts[{i}].filmstrip.count: {info['count']} != {len(times)} times"
            if any(b <= a for a, b in pairwise(times)):
                yield f"artifacts[{i}].filmstrip.times_ms: must strictly ascend"
        if kind == "proxy" and info is not None and info["tone_mapped"] != ("tone_map" in info):
            yield f"artifacts[{i}].proxy.tone_map: present exactly when tone_mapped is true"


def _instant(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def _session(doc: Document) -> Iterable[str]:
    members = doc["assets"]
    if [m["order_index"] for m in members] != list(range(len(members))):
        yield "assets: order_index must be 0, 1, 2, … in order"
    starts = [m["session_start_ms"] for m in members]
    if any(b < a for a, b in pairwise(starts)):
        yield "assets: session_start_ms must not decrease"
    ids = [m["asset_id"] for m in members]
    if len(set(ids)) != len(ids):
        yield "assets: an asset appears twice"
    started, ended = doc.get("started_at"), doc.get("ended_at")
    if started and ended and _instant(ended) < _instant(started):
        yield "ended_at: before started_at"
    grouping = doc.get("grouping")
    if grouping:
        pairs = set(pairwise(ids))
        for i, link in enumerate(grouping["links"]):
            if (link["from_asset_id"], link["to_asset_id"]) not in pairs:
                yield f"grouping.links[{i}]: must join adjacent members"


RULES: dict[str, Callable[[Document], Iterable[str]]] = {
    "session": _session,
    "derived-media": _derived_media,
    "event": _event,
    "job": _job,
    "job-event": _job_event,
    "profile": _profile,
    "project": _project,
    "render-preset": _render_preset,
    "export-manifest": _export_manifest,
    "import": _import,
    "watched-folder": _watched_folder,
}


def semantic_issues(contract: str, document: Document) -> list[str]:
    """Return human-readable semantic problems. Assumes the document passed schema validation."""
    rule = RULES.get(contract)
    return list(rule(document)) if rule else []
