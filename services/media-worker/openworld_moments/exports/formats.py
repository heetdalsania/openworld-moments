# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic open-format serializers (M27).

Every function here is pure: the same saved data always produces the same bytes.
Nothing reads the clock, the environment or the file system. Paths appear only when
the caller passes ``locations`` (the user's explicit choice), and only in project,
OTIO and FCPXML output. Anything a format cannot represent becomes a warning and,
where the format allows, is kept in an ``openworld_moments`` metadata block.
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

PROJECT_FORMAT = ("openworld-moments.project", "1.0")
EVENTS_FORMAT = ("openworld-moments.events", "1.0")
DEFAULT_RATE = 30.0  # OTIO rate when the first clip's frame rate is unknown
MAX_CAPTION_BYTES = 4 * 1024 * 1024
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class ExportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Warnings:
    """Collects one warning per code, counting repeats."""

    items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, code: str, detail: str, count: int = 1) -> None:
        if count < 1:
            return
        if code in self.items:
            self.items[code]["count"] += count
        else:
            self.items[code] = {"code": code, "detail": detail, "count": count}

    def list(self) -> list[dict[str, Any]]:
        return [self.items[k] for k in sorted(self.items)]


@dataclass(frozen=True, slots=True)
class MappedEvent:
    """An event with its effective view and where it lands on the project timeline."""

    event_id: str
    type: str
    review_state: str
    confidence: float
    start_ms: int
    end_ms: int
    project_ranges: tuple[tuple[int, int], ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def jsonl_line(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def safe_filename(title: str, extension: str, fallback: str = "project") -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip(".-_")[:80] or fallback
    if not stem[0].isalnum():
        stem = fallback
    return f"{stem}.{extension}"


# -- project editing model helpers ---------------------------------------------------


def segments_of(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    tracks = document["project"].get("tracks") or []
    return list(tracks[0]["segments"]) if tracks else []


def unsupported_operations(
    document: Mapping[str, Any], warnings: Warnings, *, captions: bool
) -> None:
    """Warn about everything an edit-decision format cannot carry."""
    project = document["project"]
    segments = segments_of(document)
    crops = sum(1 for s in segments if s.get("crop", {}).get("mode", "fit") != "fit")
    warnings.add(
        "export.crop_not_supported",
        "Crop and framing (safe, fill and manual crops) are not represented; the full "
        "source frame is referenced. Values are kept in the openworld_moments metadata.",
        crops,
    )
    warnings.add(
        "export.vertical_crop_not_supported",
        "Vertical 9:16 framing is not represented. Values are kept in the metadata.",
        sum(1 for s in segments if "vertical_crop" in s),
    )
    overlays = project.get("overlays") or []
    warnings.add(
        "export.blur_not_supported",
        "Privacy blur regions are not applied; they are kept in the metadata. Check "
        "privacy before publishing from another editor.",
        sum(1 for o in overlays if o["kind"] == "blur"),
    )
    warnings.add(
        "export.text_overlay_not_supported",
        "Text overlays are not represented as titles; they are kept in the metadata.",
        sum(1 for o in overlays if o["kind"] == "text"),
    )
    audio = project.get("audio") or {}
    gains = len(audio.get("gain_ranges") or []) + (1 if audio.get("gain_db", 0) else 0)
    warnings.add(
        "export.audio_gain_not_supported",
        "Audio gain changes are not applied; they are kept in the metadata.",
        gains,
    )
    warnings.add(
        "export.audio_mute_not_supported",
        "Mute ranges are not applied; they are kept in the metadata.",
        len(audio.get("mute_ranges") or []),
    )
    if captions:
        warnings.add(
            "export.captions_as_markers",
            "Captions are exported as markers, not caption tracks. Use the SRT or WebVTT "
            "export for caption files.",
            len(project.get("captions") or []),
        )


def missing_sources(document: Mapping[str, Any], warnings: Warnings) -> set[str]:
    missing = {s["asset_id"] for s in document["sources"] if s.get("requires_relink")}
    warnings.add(
        "export.source_missing",
        "Some sources need relinking; they are referenced by name and hash only.",
        len(missing),
    )
    return missing


# -- versioned project JSON ----------------------------------------------------------


def project_export(
    document: Mapping[str, Any],
    *,
    revision: int,
    saved_at: str,
    app_version: str,
    schema_version: str,
    locations: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The portable editor document with provenance. Lossless for this application."""
    warnings = Warnings()
    missing = missing_sources(document, warnings)
    capabilities = [
        "audio_gain",
        "audio_mute",
        "blur",
        "caption_style",
        "captions",
        "crop",
        "cuts",
        "source_hashes",
        "source_ranges",
        "text_overlays",
        "vertical_crop",
    ]
    doc: dict[str, Any] = {
        "schema_version": schema_version,
        "format": PROJECT_FORMAT[0],
        "format_version": PROJECT_FORMAT[1],
        "generator": {"name": "openworld-moments", "version": app_version},
        "project_revision": revision,
        "saved_at": saved_at,
        "capabilities": capabilities,
        "warnings": warnings.list(),
        "document": document,
        "extensions": {},
    }
    if locations is not None:
        doc["capabilities"] = sorted([*capabilities, "source_paths"])
        doc["source_locations"] = [
            {"asset_id": aid, "path": locations[aid]}
            for aid in sorted(locations)
            if aid not in missing
        ]
    return doc, warnings.list()


# -- event JSONL ---------------------------------------------------------------------


def events_jsonl(header: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> str:
    ordered = sorted(records, key=lambda r: (r["effective"]["start_ms"], r["observation"]["id"]))
    lines = [jsonl_line({**header, "event_count": len(ordered)})]
    lines.extend(jsonl_line(r) for r in ordered)
    return "".join(lines)


# -- SRT / WebVTT (byte-identical to the desktop serializer of M23) ------------------


def _valid_cues(cues: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if len(cues) > 10_000:
        raise ExportError("export.captions_invalid", "Caption limit is 10,000 cues.")
    for cue in cues:
        text = cue["text"]
        bad = (
            not isinstance(cue["start_ms"], int)
            or not isinstance(cue["end_ms"], int)
            or cue["start_ms"] < 0
            or cue["end_ms"] <= cue["start_ms"]
            or not text
            or len(text) > 1000
            or any((ord(c) < 32 and c not in "\t\n") or ord(c) == 127 for c in text)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in text)
            or text.startswith("\n")
            or text.endswith("\n")
            or any(not line.strip() for line in text.split("\n"))
        )
        if bad:
            raise ExportError(
                "export.captions_invalid",
                "Caption files need valid millisecond ranges and 1-1,000 characters "
                "without blank lines or control characters.",
            )
    # Stable sort by start, then end; ties keep their order (orderedCaptions).
    return sorted(cues, key=lambda c: (c["start_ms"], c["end_ms"]))


def _stamp(ms: int, fmt: str) -> str:
    hours, minutes, seconds = ms // 3_600_000, ms // 60_000 % 60, ms // 1000 % 60
    sep = "," if fmt == "srt" else "."
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{sep}{ms % 1000:03d}"


def _escape_vtt(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def captions_text(cues: Sequence[Mapping[str, Any]], fmt: str) -> str:
    if fmt not in ("srt", "vtt"):
        raise ExportError("export.unknown_format", "Unknown caption format.")
    blocks = [
        f"{i + 1}\n{_stamp(c['start_ms'], fmt)} --> {_stamp(c['end_ms'], fmt)}\n"
        + (_escape_vtt(c["text"]) if fmt == "vtt" else c["text"])
        for i, c in enumerate(_valid_cues(cues))
    ]
    result = ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n\n".join(blocks) + ("\n" if blocks else "")
    if len(result.encode("utf-8")) > MAX_CAPTION_BYTES:
        raise ExportError("export.too_large", "Caption file exceeds 4 MiB.")
    return result


_TIME = re.compile(r"^(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})$")


def parse_captions(text: str, fmt: str) -> list[dict[str, Any]]:
    """Read back the plain-text subset this application writes (round-trip checks)."""
    body = text.removeprefix("﻿").replace("\r\n", "\n")
    if fmt == "vtt":
        if not body.startswith("WEBVTT\n\n"):
            raise ExportError("export.captions_invalid", "Expected a plain WEBVTT header.")
        body = body[8:]
    body = body.removesuffix("\n")
    if not body:
        return []

    def stamp(value: str) -> int:
        match = _TIME.match(value)
        if not match or ("," in value) != (fmt == "srt"):
            raise ExportError("export.captions_invalid", "Invalid caption time.")
        h, m, s, ms = (int(g) for g in match.groups())
        return h * 3_600_000 + m * 60_000 + s * 1000 + ms

    cues = []
    for i, block in enumerate(body.split("\n\n")):
        lines = block.split("\n")
        if lines[0] != str(i + 1) or len(lines) < 3:
            raise ExportError("export.captions_invalid", "Expected sequential caption numbers.")
        start, _, end = lines[1].partition(" --> ")
        content = "\n".join(lines[2:])
        if fmt == "vtt":
            content = content.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        cues.append({"start_ms": stamp(start), "end_ms": stamp(end), "text": content})
    return cues


# -- CSV markers ---------------------------------------------------------------------

CSV_COLUMNS = ("kind", "label", "start", "end", "start_ms", "end_ms", "duration_ms", "detail")
_KIND_ORDER = {"cut": 0, "event": 1, "caption": 2, "text": 3, "blur": 4, "gain": 5, "mute": 6}


def _clock(ms: int) -> str:
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def _cell(text: str) -> str:
    """Neutralize spreadsheet formulas in user text (CSV injection)."""
    return "'" + text if text.startswith(FORMULA_START) else text


def csv_markers(
    document: Mapping[str, Any], events: Sequence[MappedEvent]
) -> tuple[str, list[dict[str, Any]]]:
    project = document["project"]
    names = {s["asset_id"]: s["original_name"] for s in document["sources"]}
    warnings = Warnings()
    missing_sources(document, warnings)
    rows: list[tuple[str, str, int, int, str]] = []
    for seg in segments_of(document):
        start = seg["timeline_start_ms"]
        length = seg["source_out_ms"] - seg["source_in_ms"]
        rows.append(
            (
                "cut",
                names.get(seg["asset_id"], seg["asset_id"]),
                start,
                start + length,
                f"source {seg['source_in_ms']}-{seg['source_out_ms']} ms",
            )
        )
    for event in events:
        for a, b in event.project_ranges:
            rows.append(
                (
                    "event",
                    event.type,
                    a,
                    b,
                    f"{event.review_state}, confidence {event.confidence:.2f}",
                )
            )
    for cue in project.get("captions") or []:
        rows.append(("caption", cue["text"].replace("\n", " "), cue["start_ms"], cue["end_ms"], ""))
    for overlay in project.get("overlays") or []:
        region = ",".join(f"{v:g}" for v in overlay["region"])
        label = overlay.get("text", "privacy blur") if overlay["kind"] == "text" else "privacy blur"
        rows.append(
            (overlay["kind"], label, overlay["start_ms"], overlay["end_ms"], f"region {region}")
        )
    audio = project.get("audio") or {}
    for gain in audio.get("gain_ranges") or []:
        rows.append(("gain", f"gain {gain['gain_db']:g} dB", gain["start_ms"], gain["end_ms"], ""))
    for mute in audio.get("mute_ranges") or []:
        rows.append(("mute", "mute", mute["start_ms"], mute["end_ms"], ""))
    warnings.add(
        "export.crop_not_supported",
        "Crop and vertical framing have no marker form and are not included.",
        sum(1 for s in segments_of(document) if s.get("crop", {}).get("mode", "fit") != "fit")
        + sum(1 for s in segments_of(document) if "vertical_crop" in s),
    )
    if audio.get("gain_db", 0):
        warnings.add(
            "export.audio_gain_not_supported",
            "The project-wide gain is not a timed marker and is not included.",
        )
    rows.sort(key=lambda r: (r[2], _KIND_ORDER[r[0]], r[3], r[1], r[4]))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for kind, label, a, b, detail in rows:
        writer.writerow([kind, _cell(label), _clock(a), _clock(b), a, b, b - a, _cell(detail)])
    return out.getvalue(), warnings.list()


# -- OpenTimelineIO ------------------------------------------------------------------


def _rt(ms: int, rate: float) -> dict[str, Any]:
    # Exact milliseconds expressed at the timeline's frame rate (may be fractional frames).
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": ms * rate / 1000}


def _range(start: int, duration: int, rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _rt(start, rate),
        "duration": _rt(duration, rate),
    }


def _marker(
    name: str, start: int, end: int, color: str, extra: Mapping[str, Any], rate: float
) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "Marker.2",
        "name": name,
        "marked_range": _range(start, max(0, end - start), rate),
        "color": color,
        "comment": "",
        "metadata": {"openworld_moments": dict(extra)},
    }


def _source_url(source: Mapping[str, Any], locations: Mapping[str, str] | None) -> str:
    if locations is not None and source["asset_id"] in locations:
        return locations[source["asset_id"]]
    return quote(source["original_name"])


def otio_timeline(
    document: Mapping[str, Any],
    events: Sequence[MappedEvent],
    *,
    revision: int,
    rate: float = DEFAULT_RATE,
    locations: Mapping[str, str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """OTIO JSON with one video and one audio track at ``rate`` (the first clip's)."""
    project = document["project"]
    warnings = Warnings()
    missing = missing_sources(document, warnings)
    unsupported_operations(document, warnings, captions=True)
    sources = {s["asset_id"]: s for s in document["sources"]}

    def clip(seg: Mapping[str, Any]) -> dict[str, Any]:
        source = sources[seg["asset_id"]]
        meta = {"sha256": source["sha256"], "asset_id": source["asset_id"]}
        if source["asset_id"] in missing:
            reference: dict[str, Any] = {
                "OTIO_SCHEMA": "MissingReference.1",
                "name": source["original_name"],
                "available_range": _range(0, source["duration_ms"], rate),
                "available_image_bounds": None,
                "metadata": {"openworld_moments": meta},
            }
        else:
            reference = {
                "OTIO_SCHEMA": "ExternalReference.1",
                "name": source["original_name"],
                "target_url": _source_url(source, locations),
                "available_range": _range(0, source["duration_ms"], rate),
                "available_image_bounds": None,
                "metadata": {"openworld_moments": meta},
            }
        kept = {k: seg[k] for k in ("crop", "vertical_crop") if k in seg}
        return {
            "OTIO_SCHEMA": "Clip.2",
            "name": source["original_name"],
            "source_range": _range(
                seg["source_in_ms"], seg["source_out_ms"] - seg["source_in_ms"], rate
            ),
            "media_references": {"DEFAULT_MEDIA": reference},
            "active_media_reference_key": "DEFAULT_MEDIA",
            "effects": [],
            "markers": [],
            "enabled": True,
            "metadata": {"openworld_moments": {"segment_id": seg["id"], **meta, **kept}},
        }

    segments = segments_of(document)
    markers = [
        _marker(e.type, a, b, "RED", {"event_id": e.event_id, "review_state": e.review_state}, rate)
        for e in events
        for a, b in e.project_ranges
    ] + [
        _marker(c["text"], c["start_ms"], c["end_ms"], "YELLOW", {"caption": True}, rate)
        for c in project.get("captions") or []
    ]
    markers.sort(key=lambda m: (m["marked_range"]["start_time"]["value"], m["color"], m["name"]))

    def track(name: str, kind: str, track_markers: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "OTIO_SCHEMA": "Track.1",
            "name": name,
            "kind": kind,
            "children": [clip(s) for s in segments],
            "source_range": None,
            "effects": [],
            "markers": track_markers,
            "enabled": True,
            "metadata": {},
        }

    kept_project = {
        k: project[k] for k in ("overlays", "audio", "caption_settings") if project.get(k)
    }
    timeline = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": project["title"],
        "global_start_time": None,
        "metadata": {
            "openworld_moments": {
                "format": "openworld-moments.otio",
                "format_version": "1.0",
                "project_id": project["id"],
                "project_revision": revision,
                "rate_source": "first clip frame rate" if rate != DEFAULT_RATE else "default",
                **kept_project,
            }
        },
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [track("Video", "Video", markers), track("Audio", "Audio", [])],
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "metadata": {},
        },
    }
    return canonical_json(timeline), warnings.list()


# -- FCPXML (experimental) -----------------------------------------------------------


def _t(ms: int) -> str:
    return "0s" if ms == 0 else f"{ms}/1000s"


def fcpxml(
    document: Mapping[str, Any],
    events: Sequence[MappedEvent],
    *,
    locations: Mapping[str, str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """FCPXML 1.10 spine of asset clips with markers. Experimental: times are in
    milliseconds and may not fall on frame boundaries of the importing project."""
    project = document["project"]
    warnings = Warnings()
    missing = missing_sources(document, warnings)
    unsupported_operations(document, warnings, captions=True)
    vertical = document.get("layout", {}).get("aspect_ratio") == "9:16"
    width, height = (1080, 1920) if vertical else (1920, 1080)
    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r0",
            "name": "FFVideoFormatRateUndefined",
            "frameDuration": "1/30s",
            "width": str(width),
            "height": str(height),
        },
    )
    refs: dict[str, str] = {}
    for i, source in enumerate(sorted(document["sources"], key=lambda s: s["asset_id"]), start=1):
        refs[source["asset_id"]] = f"r{i}"
        asset = ET.SubElement(
            resources,
            "asset",
            {
                "id": f"r{i}",
                "name": source["original_name"],
                "start": "0s",
                "duration": _t(source["duration_ms"]),
                "hasVideo": "1",
                "hasAudio": "1",
                "format": "r0",
                "uid": source["sha256"],
            },
        )
        if source["asset_id"] not in missing:
            src = _source_url(source, locations)
            if locations is not None and source["asset_id"] in locations:
                src = locations[source["asset_id"]]
            ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": src})
    library = ET.SubElement(root, "library")
    event_el = ET.SubElement(library, "event", {"name": "OpenWorld Moments"})
    proj = ET.SubElement(event_el, "project", {"name": project["title"]})
    segments = segments_of(document)
    total = max(
        (s["timeline_start_ms"] + s["source_out_ms"] - s["source_in_ms"] for s in segments),
        default=0,
    )
    sequence = ET.SubElement(
        proj, "sequence", {"format": "r0", "duration": _t(total), "tcStart": "0s"}
    )
    spine = ET.SubElement(sequence, "spine")
    timed = [(a, b, e.type) for e in events for a, b in e.project_ranges] + [
        (c["start_ms"], c["end_ms"], "Caption: " + c["text"].replace("\n", " "))
        for c in project.get("captions") or []
    ]
    for seg in segments:
        length = seg["source_out_ms"] - seg["source_in_ms"]
        name = next(
            s["original_name"] for s in document["sources"] if s["asset_id"] == seg["asset_id"]
        )
        clip = ET.SubElement(
            spine,
            "asset-clip",
            {
                "ref": refs[seg["asset_id"]],
                "name": name,
                "offset": _t(seg["timeline_start_ms"]),
                "start": _t(seg["source_in_ms"]),
                "duration": _t(length),
            },
        )
        lo, hi = seg["timeline_start_ms"], seg["timeline_start_ms"] + length
        for a, b, value in sorted(timed):
            if lo <= a < hi:
                # Marker times are in the clip's source time.
                ET.SubElement(
                    clip,
                    "marker",
                    {
                        "start": _t(seg["source_in_ms"] + a - lo),
                        "duration": _t(max(1, min(b, hi) - a)),
                        "value": value,
                    },
                )
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + body + "\n",
        warnings.list(),
    )
