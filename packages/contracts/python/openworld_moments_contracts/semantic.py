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
    if item["kind"] == "ocr":
        for i, line in enumerate(item.get("lines", [])):
            yield from _region(f"{path}.lines[{i}].region", line["region"])
            x, y, w, h = line["region"]
            rx, ry, rw, rh = item["region"]
            if x < rx or y < ry or x + w > rx + rw + 1e-9 or y + h > ry + rh + 1e-9:
                yield f"{path}.lines[{i}].region: line lies outside the OCR region"
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
    for name in [*doc.get("safe_zones", {}).get("preserve", []), *doc.get("subject_hints", [])]:
        if name not in doc["regions"]:
            yield f"safe_zones.preserve: '{name}' is not defined in regions"


def _project(doc: Document) -> Iterable[str]:
    if "caption_settings" in doc:
        yield from _region("caption_settings.region", doc["caption_settings"]["region"])
    for t, track in enumerate(doc["tracks"]):
        for s, seg in enumerate(track["segments"]):
            path = f"tracks[{t}].segments[{s}]"
            yield from _range(
                f"{path}.source_out_ms", seg["source_in_ms"], seg["source_out_ms"], strict=True
            )
            v = seg.get("vertical_crop")
            if v:
                keys = v["keyframes"]
                if (
                    (v["strategy"] == "fit" and keys)
                    or (v["strategy"] == "fixed" and len(keys) != 1)
                    or (v["strategy"] != "fit" and (not keys or keys[0]["at_ms"] != 0))
                ):
                    yield (
                        "vertical_crop: strategy requires fit with no keys or crop starting at zero"
                    )
                prev = -1
                for k in keys:
                    yield from _region("vertical_crop.region", k["region"])
                    if not prev < k["at_ms"] < seg["source_out_ms"] - seg["source_in_ms"]:
                        yield "vertical_crop: keys must increase inside cut"
                    if k["region"][2:] != keys[0]["region"][2:]:
                        yield "vertical_crop: interpolation requires fixed dimensions"
                    prev = k["at_ms"]
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
        if overlay["kind"] == "blur" and "keyframes" in overlay:
            keys = overlay["keyframes"]
            if not keys or keys[0]["at_ms"] != 0:
                yield "blur: keyframes must start at zero"
            previous = -1
            for k in keys:
                yield from _region("blur.keyframe.region", k["region"])
                if not previous < k["at_ms"] < overlay["end_ms"] - overlay["start_ms"]:
                    yield "blur: keyframes must increase inside range"
                if k["region"][2:] != overlay["region"][2:]:
                    yield "blur: keyframes require fixed dimensions"
                previous = k["at_ms"]
            if keys and keys[0]["region"] != overlay["region"]:
                yield "blur: region must equal first keyframe"

    for i, mute in enumerate(doc["audio"]["mute_ranges"]):
        yield from _range(
            f"audio.mute_ranges[{i}].end_ms", mute["start_ms"], mute["end_ms"], strict=True
        )

    for i, gain in enumerate(doc["audio"].get("gain_ranges", [])):
        yield from _range(
            f"audio.gain_ranges[{i}].end_ms", gain["start_ms"], gain["end_ms"], strict=True
        )


def _editor_project(doc: Document) -> Iterable[str]:
    p = doc["project"]
    from openworld_moments_contracts.versioning import check_version

    check_version("project", p)
    yield from _project(p)
    if len(p["tracks"]) != 1:
        yield "project.tracks: editor requires one primary track"
        return
    sources = {s["asset_id"]: s for s in doc["sources"]}
    if len(sources) != len(doc["sources"]):
        yield "sources: duplicate asset ID"
    segments = p["tracks"][0]["segments"]
    if len(segments) > 4096:
        yield "project.segments: limit 4096"
    position, ids = 0, set()
    for s in segments:
        length = s["source_out_ms"] - s["source_in_ms"]
        if s["id"] in ids:
            yield "project.segments: duplicate segment ID"
        ids.add(s["id"])
        if s["timeline_start_ms"] != position:
            yield "project.segments: primary track must be contiguous from zero"
        position += length
        source = sources.get(s["asset_id"])
        if source is None or s["source_out_ms"] > source["duration_ms"]:
            yield "project.segments: source binding missing or range exceeds source"
        keys = s["crop"]["keyframes"]
        if len(keys) > 1000:
            yield "project.crop: limit 1000 keyframes"
        last = -1
        for k in keys:
            if not last < k["at_ms"] < length:
                yield "project.crop: keyframes must increase inside segment"
            last = k["at_ms"]
        if s["crop"]["mode"] == "manual" and (not keys or keys[0]["at_ms"] != 0):
            yield "project.crop: manual crop needs a keyframe at zero"
    if position > 9007199254740991:
        yield "project: timeline exceeds safe integer range"
    for name, items in (
        ("captions", p["captions"]),
        ("overlays", p["overlays"]),
        ("mute_ranges", p["audio"]["mute_ranges"]),
        ("gain_ranges", p["audio"].get("gain_ranges", [])),
    ):
        if len(items) > 10000:
            yield f"project.{name}: limit 10000"
        for item in items:
            if not 0 <= item["start_ms"] < item["end_ms"] <= position:
                yield f"project.{name}: range outside timeline"
        if name == "gain_ranges":
            ordered = sorted(items, key=lambda x: x["start_ms"])
            if any(a["end_ms"] > b["start_ms"] for a, b in pairwise(ordered)):
                yield "project.gain_ranges: overlapping gain ranges"
    if ("profile_id" in doc["layout"]) != ("profile_version" in doc["layout"]):
        yield "layout: profile ID and version must be supplied together"


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
    if members and members[0].get("overlap_with_previous_ms", 0) > 0:
        yield "assets[0].overlap_with_previous_ms: the first clip has nothing before it"
    grouping = doc.get("grouping")
    if grouping:
        pairs = set(pairwise(ids))
        for i, link in enumerate(grouping["links"]):
            if (link["from_asset_id"], link["to_asset_id"]) not in pairs:
                yield f"grouping.links[{i}]: must join adjacent members"


def _overlap(doc: Document) -> Iterable[str]:
    if doc["asset_a"] == doc["asset_b"]:
        yield "asset_b: must differ from asset_a"
    if doc["status"] == "matched":
        for field in ("offset_ms", "overlap_ms", "confidence"):
            if field not in doc:
                yield f"{field}: required when status is 'matched'"
    applied = doc["applied"]
    override = doc.get("override")
    if override is not None and (
        applied["source"] != "user" or applied["overlap_ms"] != override["overlap_ms"]
    ):
        yield "applied: must be the override when one is set"
    if (
        override is None
        and applied["source"] == "auto"
        and (doc["status"] != "matched" or not doc["current"])
    ):
        yield "applied: only a current matched result can be applied"


def _transcript(doc: Document) -> Iterable[str]:
    previous = None
    for i, seg in enumerate(doc["segments"]):
        path = f"segments[{i}]"
        yield from _range(f"{path}.end_ms", seg["start_ms"], seg["end_ms"])
        yield from _range(f"{path}.source_end_ms", seg["source_start_ms"], seg["source_end_ms"])
        if previous is not None and seg["start_ms"] < previous:
            yield f"{path}.start_ms: segments must be ordered by session time"
        previous = seg["start_ms"]
        last = seg["start_ms"]
        for j, word in enumerate(seg["words"]):
            wpath = f"{path}.words[{j}]"
            yield from _range(f"{wpath}.end_ms", word["start_ms"], word["end_ms"])
            yield from _range(
                f"{wpath}.source_end_ms", word["source_start_ms"], word["source_end_ms"]
            )
            if word["start_ms"] < seg["start_ms"] or word["end_ms"] > seg["end_ms"]:
                yield f"{wpath}: word lies outside its segment"
            if word["start_ms"] < last:
                yield f"{wpath}.start_ms: words must be ordered"
            last = word["start_ms"]


def _transcription(doc: Document) -> Iterable[str]:
    seen: set[str] = set()
    for i, outcome in enumerate(doc["outcomes"]):
        if outcome["asset_id"] in seen:
            yield f"outcomes[{i}].asset_id: each clip appears once"
        seen.add(outcome["asset_id"])


def _speech_models(doc: Document) -> Iterable[str]:
    names = [m["name"] for m in doc["installed"]]
    if len(names) != len(set(names)):
        yield "installed: model names must be unique"
    if not doc["engine"]["available"] and "reason" not in doc["engine"]:
        yield "engine.reason: required when the engine is unavailable"


def _evaluation(doc: Document) -> Iterable[str]:
    hashes = [c["sha256"] for c in doc["clips"]]
    if len(hashes) != len(set(hashes)):
        yield "clips: media hashes must be unique"
    for i, clip in enumerate(doc["clips"]):
        for j, event in enumerate(clip.get("annotations", clip.get("events", []))):
            if event["end_ms"] < event["start_ms"] or event["end_ms"] > clip.get(
                "duration_ms", float("inf")
            ):
                yield f"clips[{i}].intervals[{j}]: invalid clip interval"
    if "detectors" in doc:
        ids = [d["id"] for d in doc["detectors"]]
        if len(ids) != len(set(ids)):
            yield "detectors: IDs must be unique"


def _event_review(doc: Document) -> Iterable[str]:
    if doc["offset"] + len(doc["items"]) > max(doc["total"], doc["offset"]):
        yield "items: page exceeds total"
    ids = [i["original"]["id"] for i in doc["items"]]
    if len(ids) != len(set(ids)):
        yield "items: event IDs must be unique"
    for i, item in enumerate(doc["items"]):
        a, b = item["original"], item["effective"]
        for name, event in (("original", a), ("effective", b)):
            for issue in _event(event):
                yield f"items[{i}].{name}.{issue}"
        if a["session_id"] != doc["session_id"] or any(
            a.get(k) != b.get(k)
            for k in (
                "id",
                "session_id",
                "asset_id",
                "confidence",
                "evidence",
                "source",
                "attributes",
            )
        ):
            yield f"items[{i}]: immutable observation fields differ"
        if item["status"] == "current" and b["end_ms"] > doc["duration_ms"]:
            yield f"items[{i}].effective.end_ms: outside current session"
        revisions = [d["revision"] for d in item["history"]]
        if revisions and (revisions != sorted(set(revisions)) or revisions[-1] != item["revision"]):
            yield f"items[{i}].history: revisions must ascend to current revision"
        for j, decision in enumerate(item["history"]):
            yield from _range(
                f"items[{i}].history[{j}].end_ms", decision["start_ms"], decision["end_ms"]
            )


def _story_ranges(ranges: list[Document], start: int, end: int) -> Iterable[str]:
    position = start
    used: dict[str, list[tuple[int, int]]] = {}
    for r in ranges:
        if (
            r["session_start_ms"] != position
            or r["session_end_ms"] <= position
            or r["source_out_ms"] - r["source_in_ms"] != r["session_end_ms"] - position
        ):
            yield (
                "source_ranges: ranges must cover the window exactly without gaps or duplicate time"
            )
        for a, b in used.get(r["asset_id"], []):
            if r["source_in_ms"] < b and a < r["source_out_ms"]:
                yield "source_ranges: duplicate source footage"
        used.setdefault(r["asset_id"], []).append((r["source_in_ms"], r["source_out_ms"]))
        position = r["session_end_ms"]
    if position != end:
        yield "source_ranges: end differs from the window"


def _story_candidate(doc: Document) -> Iterable[str]:
    yield from _range("end_ms", doc["start_ms"], doc["end_ms"], strict=True)
    maximum = {"moment": 25000, "short": 60000, "extended_short": 180000, "highlight": 120000}[
        doc["preset"]
    ]
    if doc["end_ms"] - doc["start_ms"] > maximum:
        yield "end_ms: preset maximum exceeded"
    yield from _story_ranges(doc["source_ranges"], doc["start_ms"], doc["end_ms"])
    ids = [e["event_id"] for e in doc["source_events"]]
    if len(ids) != len(set(ids)):
        yield "source_events: event IDs must be unique"
    for e in doc["source_events"]:
        yield from _range("source_events.end_ms", e["start_ms"], e["end_ms"], strict=True)
    for b in doc["beats"]:
        yield from _range("beats.end_ms", b["start_ms"], b["end_ms"], strict=True)
        if b["start_ms"] < doc["start_ms"] or b["end_ms"] > doc["end_ms"]:
            yield "beats: outside candidate window"
        if not set(b["event_ids"]) <= set(ids):
            yield "beats: unknown source event"
    if abs(sum(doc["score_components"].values()) - doc["score"]) > 0.0000011:
        yield "score: must equal the sum of score_components"
    positive = {
        "event_confidence": 0.25,
        "setup_coverage": 0.15,
        "payoff_coverage": 0.2,
        "reaction_evidence": 0.1,
        "continuity_score": 0.3,
    }
    negative = {
        "duplicate_penalty": 0,
        "dead_air_penalty": 0.15,
        "truncation_penalty": 0.25,
        "spoiler_risk_penalty": 0.1,
        "rejection_penalty": 0.2,
        "missing_payoff_penalty": 0.1,
    }
    if any(not 0 <= doc["score_components"][k] <= v for k, v in positive.items()) or any(
        not -v <= doc["score_components"][k] <= 0 for k, v in negative.items()
    ):
        yield "score_components: component outside documented weight"
    seen = set()
    for a in doc["alternatives"]:
        yield from _range("alternatives.end_ms", a["start_ms"], a["end_ms"], strict=True)
        if a["end_ms"] - a["start_ms"] > maximum or a["kind"] in seen:
            yield "alternatives: preset maximum or unique kind violated"
        seen.add(a["kind"])
        yield from _story_ranges(a["source_ranges"], a["start_ms"], a["end_ms"])


def _story_candidates(doc: Document) -> Iterable[str]:
    ids = [i["candidate"]["id"] for i in doc["items"]]
    if len(ids) != len(set(ids)) or (ids and doc["offset"] + len(ids) > doc["total"]):
        yield "items: duplicate IDs or inconsistent page total"
    for item in doc["items"]:
        c = item["candidate"]
        yield from _story_candidate(c)
        if c["session_id"] != doc["session_id"]:
            yield "items: foreign session"
        if item["current"] and (
            c["input_key"] != doc["input_key"]
            or c["layout_key"] != doc["layout_key"]
            or c["generator"] != doc["generator"]
            or c["end_ms"] > doc["duration_ms"]
        ):
            yield "items: current candidate identity or timing differs"
        if item["revision"] == 0 and item["review_state"] != "suggested":
            yield "items: unrecorded review decision"
        if item.get("project_id", c["id"]) != c["id"]:
            yield "items: project ID differs from candidate"


def _render(doc: Document) -> Iterable[str]:
    plan = doc.get("plan")
    if plan is not None:
        sources = len(plan["sources"])
        for i, source in enumerate(plan["sources"]):
            if source["index"] != i:
                yield f"plan.sources[{i}].index: sources are numbered in order"
        expected = 0
        for i, seg in enumerate(plan["segments"]):
            path = f"plan.segments[{i}]"
            if seg["source"] >= sources:
                yield f"{path}.source: no such source"
            yield from _range(f"{path}.out_ms", seg["in_ms"], seg["out_ms"], strict=True)
            if seg["timeline_start_ms"] != expected:
                yield f"{path}.timeline_start_ms: segments are contiguous from zero"
            expected += seg["out_ms"] - seg["in_ms"]
            if seg["crop"]["mode"] == "manual" and "region" not in seg["crop"]:
                yield f"{path}.crop.region: required for a manual crop"
        if expected != plan["duration_ms"]:
            yield "plan.duration_ms: must equal the sum of segment durations"
    if doc["status"] == "ready" and not doc["validation"]["passed"]:
        yield "validation.passed: a ready render has passed validation"
    if doc["status"] != "failed" and "fallback" in doc:
        yield "fallback: only a failed render offers a fallback"


def _render_encoders(doc: Document) -> Iterable[str]:
    ids = [e["id"] for e in doc["encoders"]]
    if len(ids) != len(set(ids)):
        yield "encoders: each encoder appears once"
    for i, encoder in enumerate(doc["encoders"]):
        if (encoder["id"] == "libx264") != (encoder["kind"] == "cpu"):
            yield f"encoders[{i}].kind: libx264 is the CPU encoder; others are hardware"
        if not encoder["available"] and "reason" not in encoder:
            yield f"encoders[{i}].reason: required when unavailable"


_ID_FIELD = {
    "clip": "asset_id",
    "session": "session_id",
    "event": "event_id",
    "transcript": "transcript_id",
    "project": "project_id",
}


def _search_result(path: str, item: Document) -> Iterable[str]:
    prefix, _, ident = item["key"].partition(":")
    if prefix != item["kind"]:
        yield f"{path}.key: must start with the result kind"
    field = _ID_FIELD[item["kind"]]
    if str(item.get(field, "")) != ident:
        yield f"{path}.{field}: must match the key"
    span = item.get("range")
    if span is not None:
        yield from _range(f"{path}.range.end_ms", span["start_ms"], span["end_ms"])
        if (span["timebase"] == "clip") != (item["kind"] == "clip"):
            yield f"{path}.range.timebase: clip results use clip time; others session time"
    source = item.get("source_range")
    if source is not None:
        yield from _range(f"{path}.source_range.end_ms", source["start_ms"], source["end_ms"])
        if source["asset_id"] != item.get("asset_id"):
            yield f"{path}.source_range.asset_id: must match the result clip"


def _page(doc: Document, limit: int) -> Iterable[str]:
    if len(doc["items"]) > limit:
        yield "items: more items than the page limit"
    if doc["items"] and doc["offset"] + len(doc["items"]) > doc["total"]:
        yield "total: smaller than offset plus items on this page"
    keys = [item["key"] for item in doc["items"]]
    if len(keys) != len(set(keys)):
        yield "items: each result appears once"
    for i, item in enumerate(doc["items"]):
        yield from _search_result(f"items[{i}]", item)


def _search(doc: Document) -> Iterable[str]:
    yield from _page(doc, doc["limit"])
    for i, item in enumerate(doc["items"]):
        if "reasons" in item or "item_id" in item:
            yield f"items[{i}]: only collection items carry reasons or item IDs"
    for name, facets in doc["facets"].items():
        values = [f["value"] for f in facets]
        if len(values) != len(set(values)):
            yield f"facets.{name}: each value appears once"
        for j, facet in enumerate(facets):
            if facet["count"] > doc["total"]:
                yield f"facets.{name}[{j}].count: cannot exceed total"


def _search_index(doc: Document) -> Iterable[str]:
    reasons = doc["reasons"]
    if (doc["status"] == "current") != (not reasons):
        yield "reasons: a current index has no reasons; any other status has one"
    if (doc["status"] == "corrupt") != ("full_text_corrupt" in reasons):
        yield "status: corrupt exactly when the full-text index failed its check"
    if "full_text_corrupt" in reasons and not doc["checked"]:
        yield "checked: corruption is only reported by a full check"
    if (doc["index_version"] != doc["expected_version"]) != ("version_changed" in reasons):
        yield "reasons: version_changed exactly when the index version differs"


def _collection(doc: Document) -> Iterable[str]:
    yield from _page(doc, 100)
    if doc["kind"] == "manual" and "rule" in doc:
        yield "rule: only rule-based collections have a rule"
    if doc["kind"] == "rule" and "item_count" in doc:
        yield "item_count: rule-based collections have no stored items"
    for i, item in enumerate(doc["items"]):
        if doc["kind"] == "rule":
            if "reasons" not in item:
                yield f"items[{i}].reasons: rule-based items explain why they matched"
            if "item_id" in item:
                yield f"items[{i}].item_id: rule-based collections have no stored items"
        else:
            if "reasons" in item:
                yield f"items[{i}].reasons: manual items were added by hand"
            if "item_id" not in item or "added_at" not in item:
                yield f"items[{i}]: manual items carry item_id and added_at"
    if doc["kind"] == "manual" and doc.get("item_count") != doc["total"]:
        yield "total: must equal item_count for a manual collection"


_PATH_FORMATS = frozenset({"project", "otio", "fcpxml"})


def _export_result(doc: Document) -> Iterable[str]:
    if (doc["stability"] == "experimental") != (doc["format"] == "fcpxml"):
        yield "stability: FCPXML is experimental; every other format is stable"
    if doc["includes_paths"] and doc["format"] not in _PATH_FORMATS:
        yield "includes_paths: only project, OTIO and FCPXML exports may carry paths"


def _project_export(doc: Document) -> Iterable[str]:
    known = {s["asset_id"] for s in doc["document"]["sources"]}
    seen: set[str] = set()
    for i, location in enumerate(doc.get("source_locations", [])):
        if location["asset_id"] not in known:
            yield f"source_locations[{i}].asset_id: not a source of the document"
        if location["asset_id"] in seen:
            yield f"source_locations[{i}].asset_id: each source appears once"
        seen.add(location["asset_id"])


def _event_export(doc: Document) -> Iterable[str]:
    if doc["record"] != "event":
        return
    effective = doc["effective"]
    yield from _range("effective.end_ms", effective["start_ms"], effective["end_ms"])
    for i, span in enumerate(doc.get("project_ranges", [])):
        yield from _range(
            f"project_ranges[{i}].end_ms", span["start_ms"], span["end_ms"], strict=True
        )


def _privacy_review(doc: Document) -> Iterable[str]:
    ids = set()
    for f in doc["flags"]:
        yield from _range("privacy.flag.end_ms", f["start_ms"], f["end_ms"], strict=True)
        if "region" in f:
            yield from _region("privacy.flag.region", f["region"])
        if f["id"] in ids:
            yield "privacy: duplicate finding"
        ids.add(f["id"])
        has_source = sum(k in f for k in ("asset_id", "source_start_ms", "source_end_ms"))
        if has_source not in (0, 3):
            yield "privacy: source range requires all fields"
        if "source_start_ms" in f and "source_end_ms" in f:
            yield from _range(
                "privacy.source_end_ms", f["source_start_ms"], f["source_end_ms"], strict=True
            )
    for r in doc["config"]["ranges"]:
        yield from _range("privacy.spoiler.end_ms", r["start_ms"], r["end_ms"], strict=True)
    if doc["summary"]["token"] != doc["token"]:
        yield "privacy: summary token differs"
    if doc["summary"]["unresolved"] != sum(f["decision"] == "unresolved" for f in doc["flags"]):
        yield "privacy: unresolved count differs"
    if doc["current"] != (doc["summary"]["acknowledged"] and doc["summary"]["unresolved"] == 0):
        yield "privacy: gate state differs"
    if doc["summary"]["findings"] != [
        dict(id=f["id"], category=f["category"], state=f["decision"]) for f in doc["flags"]
    ]:
        yield "privacy: summary decisions differ"


RULES: dict[str, Callable[[Document], Iterable[str]]] = {
    "privacy-review": _privacy_review,
    "event-export": _event_export,
    "export-result": _export_result,
    "project-export": _project_export,
    "collection": _collection,
    "search": _search,
    "search-index": _search_index,
    "render": _render,
    "render-encoders": _render_encoders,
    "story-candidate": _story_candidate,
    "story-candidates": _story_candidates,
    "evaluation": _evaluation,
    "evaluation-observations": _evaluation,
    "event-review": _event_review,
    "transcript": _transcript,
    "transcription": _transcription,
    "speech-models": _speech_models,
    "overlap": _overlap,
    "session": _session,
    "derived-media": _derived_media,
    "event": _event,
    "job": _job,
    "job-event": _job_event,
    "profile": _profile,
    "profile-patch": lambda doc: (
        issue for name, r in doc["regions"].items() for issue in _region(f"regions.{name}", r)
    ),
    "project": _project,
    "editor-project": _editor_project,
    "render-preset": _render_preset,
    "export-manifest": _export_manifest,
    "import": _import,
    "watched-folder": _watched_folder,
}


def semantic_issues(contract: str, document: Document) -> list[str]:
    """Return human-readable semantic problems. Assumes the document passed schema validation."""
    rule = RULES.get(contract)
    return list(rule(document)) if rule else []
