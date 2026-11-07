# SPDX-License-Identifier: AGPL-3.0-or-later
"""Versioned, deterministic metadata-only story windows. No model or media calls."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openworld_moments.detectors.profiles import digest

GENERATOR_VERSION = "1.0.0"
GENERATOR_ID = "owm-story"
# min, max, pre-roll, post-roll, causal gap (milliseconds).
PRESETS = {
    "moment": (10000, 25000, 4000, 4000, 3000),
    "short": (25000, 60000, 10000, 8000, 10000),
    "extended_short": (60000, 180000, 15000, 12000, 20000),
    "highlight": (30000, 120000, 12000, 10000, 15000),
}
PAYOFFS = frozenset(
    {
        "openworld.player_died",
        "openworld.player_arrested",
        "openworld.mission_completed",
        "openworld.mission_failed",
        "openworld.vehicle_crash",
        "openworld.escape",
    }
)
SUPPORT = frozenset(
    {
        "openworld.subtitle",
        "openworld.dialogue",
        "openworld.silence",
        "openworld.speech_activity",
        "openworld.scene_boundary",
        "openworld.scene_cut",
    }
)


class StoryLimitError(Exception):
    """Bounded candidate/reference output would be exceeded."""


def generator() -> dict[str, str]:
    return {"id": GENERATOR_ID, "version": GENERATOR_VERSION}


def stable_id(prefix: str, value: Any) -> str:
    """Content-addressed, 128-bit ID in the existing ULID-shaped contract alphabet.

    Unlike new_ulid, the hash portion does not represent a creation timestamp.
    """
    n = int(digest(value)[:32], 16)
    chars = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out = ""
    for _ in range(26):
        out = chars[n & 31] + out
        n >>= 5
    return f"{prefix}_{out}"


def support(e: dict[str, Any]) -> bool:
    # Original supporting audio can never become a seed through relabeling.
    return bool(e["supporting"] or e["type"] in SUPPORT or e["type"].startswith("openworld.audio_"))


def eligible(e: dict[str, Any], options: dict[str, Any]) -> bool:
    if e["review_state"] == "rejected" or support(e):
        return False
    return e["review_state"] in ("confirmed", "corrected") or (
        options["allow_unreviewed"] and e["source_kind"] == "detector" and e["confidence"] >= 0.9
    )


def beat_kind(e: dict[str, Any]) -> str:
    if e["type"] in PAYOFFS:
        return "payoff"
    if e["type"] == "openworld.wanted_level_changed":
        before, after = e.get("from"), e.get("to")
        if isinstance(before, int) and isinstance(after, int):
            if before > 0 and after == 0:
                return "payoff"
            if after > before > 0:
                return "escalation"
    return "incident"


def related(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["type"] == b["type"] == "openworld.wanted_level_changed") or bool(
        a["type"].startswith("openworld.mission_") and b["type"].startswith("openworld.mission_")
    )


def source_ranges(members: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    ranges = []
    for m in members:
        a, b = max(start, m["start_ms"]), min(end, m["end_ms"])
        if a < b:
            ranges.append(
                {
                    "asset_id": m["asset_id"],
                    "source_in_ms": m["hidden_ms"] + a - m["start_ms"],
                    "source_out_ms": m["hidden_ms"] + b - m["start_ms"],
                    "session_start_ms": a,
                    "session_end_ms": b,
                }
            )
    return ranges


def speech_cuts(spans: list[tuple[int, int]], start: int, end: int) -> int:
    return sum(a < start < b or a < end < b for a, b in spans)


def bounds(
    events: list[dict[str, Any]],
    snapshot: dict[str, Any],
    preset: str,
    options: dict[str, Any],
    factor: float = 1,
) -> tuple[int, int, bool]:
    minimum, maximum, *_ = PRESETS[preset]
    duration = snapshot["duration_ms"]
    first, last = min(e["start_ms"] for e in events), max(e["end_ms"] for e in events)
    start = max(0, first - round(options["pre_roll_ms"] * factor))
    end = min(duration, last + round(options["post_roll_ms"] * factor))
    pressure = end - start > maximum
    if pressure:
        payoffs = [e for e in events if beat_kind(e) == "payoff"]
        anchor = (
            payoffs[-1]
            if payoffs
            else max(events, key=lambda e: (e["confidence"], -e["start_ms"], e["event_id"]))
        )
        end = min(duration, anchor["end_ms"] + round(options["post_roll_ms"] * factor))
        start = max(0, end - maximum)
        if anchor["start_ms"] < start and anchor["end_ms"] - anchor["start_ms"] <= maximum:
            start = anchor["start_ms"]
            end = min(duration, start + maximum)
    if end - start < minimum:
        missing = minimum - (end - start)
        start = max(0, start - (missing + 1) // 2)
        end = min(duration, max(end, start + minimum))
        start = max(0, min(start, end - minimum))
    # Expand to whole utterances/sentences. Iterate because one expansion can
    # intersect another overlapping speaker's sentence. If impossible, expose it.
    spans = snapshot["speech"]
    for _ in range(len(spans) + 1):
        a, b = start, end
        for left, right in spans:
            if left < a < right:
                a = left
            if left < b < right:
                b = right
        if (a, b) == (start, end):
            break
        if b - a > maximum:
            # Try shifting away from the cut while preserving every seed that
            # survived duration pressure. Never fix speech by silently losing it.
            retained = [e for e in events if start <= e["start_ms"] and e["end_ms"] <= end]
            if retained:
                lo, hi = min(e["start_ms"] for e in retained), max(e["end_ms"] for e in retained)
                choices = [(a, min(duration, a + maximum)), (max(0, b - maximum), b)]
                valid = [
                    (x, y)
                    for x, y in choices
                    if x <= lo and hi <= y and not speech_cuts(spans, x, y)
                ]
                if valid:
                    start, end = min(valid, key=lambda p: (abs(p[0] - start) + abs(p[1] - end), p))
            break
        start, end = a, b
    # Prefer nearby OUTWARD silence midpoints / explicit scene markers. This
    # cannot remove setup/payoff context and never treats noise as a scene cut.
    for edge in (0, 1):
        value = start if edge == 0 else end
        points = [
            p
            for p in snapshot["boundaries"]
            if (value - 2000 <= p <= value if edge == 0 else value <= p <= value + 2000)
        ]
        for point in sorted(points, key=lambda p: (abs(p - value), p)):
            a, b = (point, end) if edge == 0 else (start, point)
            if 0 <= a < b <= duration and b - a <= maximum and not speech_cuts(spans, a, b):
                start, end = a, b
                break
    return start, end, pressure


def union_duration(intervals: list[tuple[int, int]]) -> int:
    total = 0
    end = 0
    for a, b in sorted(intervals):
        total += max(0, b - max(a, end))
        end = max(end, b)
    return total


def make_candidate(
    snapshot: dict[str, Any], events: list[dict[str, Any]], preset: str, options: dict[str, Any]
) -> dict[str, Any]:
    start, end, pressure = bounds(events, snapshot, preset, options)
    included = [e for e in events if e["start_ms"] < end and e["end_ms"] > start]
    # The anchor always intersects. Supporting/rejected evidence is recorded by
    # exact revision too, so every bonus/penalty can be inspected without text.
    context = [
        e
        for e in snapshot["events"]
        if e not in included
        and e["start_ms"] < end
        and e["end_ms"] > start
        and (support(e) or e["review_state"] == "rejected")
    ]
    refs = sorted(events + context, key=lambda e: (e["start_ms"], e["event_id"]))
    beats = []
    first = min(e["start_ms"] for e in events)
    setup = min(1.0, max(0, first - start) / max(1, options["pre_roll_ms"]))
    if start < first:
        beats.append(
            {
                "kind": "setup",
                "start_ms": start,
                "end_ms": first,
                "event_ids": [],
                "basis": "context",
            }
        )
    for e in included:
        beats.append(
            {
                "kind": beat_kind(e),
                "start_ms": max(start, e["start_ms"]),
                "end_ms": min(end, e["end_ms"]),
                "event_ids": [e["event_id"]],
                "basis": "event",
            }
        )
    payoffs = [
        e
        for e in included
        if beat_kind(e) == "payoff" and start <= e["start_ms"] and e["end_ms"] <= end
    ]
    reaction = False
    if payoffs:
        after = max(e["end_ms"] for e in payoffs)
        # A post-event utterance is evidence of speech, not an inferred emotion.
        for a, b in snapshot["speech"]:
            if after <= a < b <= end:
                beats.append(
                    {
                        "kind": "reaction",
                        "start_ms": a,
                        "end_ms": b,
                        "event_ids": [],
                        "basis": "transcript",
                    }
                )
                reaction = True
                break
        if not reaction:
            for e in context:
                if (
                    e["supporting"]
                    and e["review_state"] != "rejected"
                    and after <= e["start_ms"] < e["end_ms"] <= end
                    and e["type"]
                    in (
                        "openworld.audio_impact",
                        "openworld.audio_onset",
                        "openworld.speech_activity",
                    )
                ):
                    beats.append(
                        {
                            "kind": "reaction",
                            "start_ms": e["start_ms"],
                            "end_ms": e["end_ms"],
                            "event_ids": [e["event_id"]],
                            "basis": "audio",
                        }
                    )
                    reaction = True
                    break
    speech = speech_cuts(snapshot["speech"], start, end)
    truncated = any(e["start_ms"] < start or e["end_ms"] > end for e in events)
    silence = union_duration(
        [
            (max(start, e["start_ms"]), min(end, e["end_ms"]))
            for e in context
            if e["type"] == "openworld.silence" and e["review_state"] != "rejected"
        ]
    )
    rejected = [e for e in context if e["review_state"] == "rejected"]
    components = {
        "event_confidence": round(0.25 * sum(e["confidence"] for e in included) / len(included), 6),
        "setup_coverage": round(0.15 * setup, 6),
        "payoff_coverage": 0.2 if payoffs else 0,
        "reaction_evidence": 0.1 if reaction else 0,
        "continuity_score": 0.3,
        "duplicate_penalty": 0,
        "dead_air_penalty": round(-0.15 * silence / (end - start), 6),
        "truncation_penalty": -0.25 if speech or truncated else 0,
        "spoiler_risk_penalty": -0.1
        if options["avoid_spoilers"] and any(e["spoiler_risk"] for e in included)
        else 0,
        "rejection_penalty": -0.2 if rejected else 0,
        "missing_payoff_penalty": 0 if payoffs else -0.1,
    }
    warnings = []
    if not payoffs:
        warnings.append("missing_payoff")
    if pressure or truncated:
        warnings.append("duration_pressure")
    if speech:
        warnings.append("speech_truncated")
    if end - start < PRESETS[preset][0]:
        warnings.append("below_minimum")
    if any(e["review_state"] == "unreviewed" for e in included):
        warnings.append("unreviewed_seed")
    alternatives = []
    seen = {(start, end)}
    for name, factor in (("short", 0.5), ("long", 1.5)):
        a, b, _ = bounds(events, snapshot, preset, options, factor)
        length = b - a
        preferred = length <= end - start if name == "short" else length >= end - start
        if (a, b) not in seen and preferred:
            alternatives.append(
                {
                    "kind": name,
                    "start_ms": a,
                    "end_ms": b,
                    "source_ranges": source_ranges(snapshot["members"], a, b),
                    "speech_truncated": bool(speech_cuts(snapshot["speech"], a, b)),
                }
            )
            seen.add((a, b))
    doc = {
        "schema_version": "1.15",
        "session_id": snapshot["session_id"],
        "generator": generator(),
        "input_key": snapshot["input_key"],
        "layout_key": snapshot["layout_key"],
        "preset": preset,
        "options": options,
        "start_ms": start,
        "end_ms": end,
        "source_events": [
            {
                k: e[k]
                for k in (
                    "event_id",
                    "revision",
                    "type",
                    "start_ms",
                    "end_ms",
                    "review_state",
                    "confidence",
                )
            }
            for e in refs
        ],
        "source_ranges": source_ranges(snapshot["members"], start, end),
        "beats": beats,
        "alternatives": alternatives,
        "score": round(sum(components.values()), 6),
        "score_components": components,
        "metrics": {
            "setup_coverage": round(setup, 6),
            "payoff_coverage": int(bool(payoffs)),
            "speech_truncations": speech,
            "duplicate_ms": 0,
        },
        "warnings": warnings,
    }
    return {"id": stable_id("prj", doc), **doc}


def generate(
    snapshot: dict[str, Any],
    preset: str,
    options: dict[str, Any],
    check: Callable[[], None] = lambda: None,
) -> list[dict[str, Any]]:
    check()
    seeds = sorted(
        [e for e in snapshot["events"] if eligible(e, options)],
        key=lambda e: (e["start_ms"], e["end_ms"], e["event_id"]),
    )
    groups: list[list[dict[str, Any]]] = []
    for e in seeds:
        check()
        if groups:
            previous = groups[-1]
            last = max(x["end_ms"] for x in previous)
            overlap = e["start_ms"] - options["pre_roll_ms"] <= last + options["post_roll_ms"]
            causal = e["start_ms"] - last <= options["merge_gap_ms"] and related(previous[-1], e)
            if overlap or causal:
                previous.append(e)
                continue
        groups.append([e])
    if len(groups) > 1000:
        raise StoryLimitError
    out = []
    references = 0
    for group in groups:
        check()
        doc = make_candidate(snapshot, group, preset, options)
        references += len(doc["source_events"])
        if references > 50000:
            raise StoryLimitError
        out.append(doc)
    # Duration constraints can move neighboring groups onto the same footage.
    # Coalesce those groups, then regenerate once per union, never duplicate it.
    while len(out) > 1:
        check()
        merged = False
        for i in range(len(out) - 1):
            if out[i]["end_ms"] >= out[i + 1]["start_ms"]:
                groups[i].extend(groups.pop(i + 1))
                out[i : i + 2] = [make_candidate(snapshot, groups[i], preset, options)]
                if sum(len(d["source_events"]) for d in out) > 50000:
                    raise StoryLimitError
                merged = True
                break
        if not merged:
            break
    return sorted(out, key=lambda d: (d["start_ms"], d["id"]))
