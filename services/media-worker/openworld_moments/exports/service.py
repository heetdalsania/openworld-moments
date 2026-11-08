# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open-format exports of saved projects and render manifests (M27).

Reads only committed data (the saved editor revision, never an unsaved recovery
draft), so re-exporting unchanged data returns identical bytes. Nothing here writes
the database or touches media. Absolute source paths are included only when the
caller passes ``include_paths`` and only for formats that can reference media.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments import __version__
from openworld_moments.exports.formats import (
    DEFAULT_RATE,
    EVENTS_FORMAT,
    ExportError,
    MappedEvent,
    canonical_json,
    captions_text,
    csv_markers,
    events_jsonl,
    fcpxml,
    otio_timeline,
    project_export,
    safe_filename,
)
from openworld_moments.ingest.library import LibraryPaths, readable_source
from openworld_moments.privacy.service import PrivacyReviewService
from openworld_moments.projects.service import ProjectService
from openworld_moments.review.service import layout_info
from openworld_moments.storage import AssetRepository, Database, NotFoundError
from openworld_moments.storage.repositories import SCHEMA_VERSION, EventRepository

_SLUG = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")

#: format -> (extension, media type, stability, can carry paths)
FORMATS: dict[str, tuple[str, str, str, bool]] = {
    "project": ("owm.json", "application/json", "stable", True),
    "events": ("jsonl", "application/jsonl", "stable", False),
    "srt": ("srt", "application/x-subrip", "stable", False),
    "vtt": ("vtt", "text/vtt", "stable", False),
    "csv": ("csv", "text/csv", "stable", False),
    "otio": ("otio", "application/vnd.opentimelineio+json", "stable", True),
    "fcpxml": ("fcpxml", "application/xml", "experimental", True),
}
FORMAT_VERSIONS = {
    "project": "1.0",
    "events": "1.0",
    "srt": "1.0",
    "vtt": "1.0",
    "csv": "1.0",
    "otio": "1.0",
    "fcpxml": "1.10-experimental",
    "manifest": "1.0",
}
CAPABILITIES = {
    "events": ["events", "evidence", "provenance", "review_state", "project_ranges"],
    "srt": ["captions"],
    "vtt": ["captions"],
    "csv": ["audio_gain", "audio_mute", "blur", "captions", "cuts", "events", "text_overlays"],
    "otio": ["captions_as_markers", "cuts", "events", "metadata", "source_hashes", "source_ranges"],
    "fcpxml": ["captions_as_markers", "cuts", "events", "source_ranges"],
    "manifest": ["detectors", "encoder", "output_hash", "preset", "profiles", "source_hashes"],
}


class ExportFailed(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _envelope(
    fmt: str,
    content: str,
    filename: str,
    warnings: Sequence[Mapping[str, Any]],
    capabilities: Sequence[str],
    includes_paths: bool,
) -> dict[str, Any]:
    media_type = "application/json" if fmt == "manifest" else FORMATS[fmt][1]
    stability = "stable" if fmt == "manifest" else FORMATS[fmt][2]
    return normalize(
        load(
            "export-result",
            {
                "schema_version": SCHEMA_VERSION,
                "format": fmt,
                "format_version": FORMAT_VERSIONS[fmt],
                "stability": stability,
                "filename": filename,
                "media_type": media_type,
                "content": content,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "capabilities": sorted(capabilities),
                "warnings": list(warnings),
                "includes_paths": includes_paths,
            },
        )
    )


def session_layout(conn: sqlite3.Connection, session_id: str) -> list[tuple[str, int, int, int]]:
    """Members as (asset_id, unique_start_ms, hidden_head_ms, visible_ms), in order."""
    rows = conn.execute(
        "SELECT sa.asset_id, a.duration_ms, sa.overlap_with_previous_ms FROM session_assets sa "
        "JOIN media_assets a ON a.id = sa.asset_id WHERE sa.session_id = ? ORDER BY sa.order_index",
        (session_id,),
    ).fetchall()
    layout, at = [], 0
    for i, (aid, duration, overlap) in enumerate(rows):
        hidden = min(duration, overlap) if i else 0
        visible = max(0, duration - hidden)
        layout.append((aid, at, hidden, visible))
        at += visible
    return layout


def project_ranges(
    layout: Sequence[tuple[str, int, int, int]],
    segments: Sequence[Mapping[str, Any]],
    start_ms: int,
    end_ms: int,
) -> tuple[tuple[int, int], ...]:
    """Where a unique-session interval lands on the project timeline (may be nowhere)."""
    spans: list[tuple[int, int]] = []
    for aid, unique, hidden, visible in layout:
        a, b = max(start_ms, unique), min(end_ms, unique + visible)
        if a >= b:
            continue
        src_a, src_b = hidden + a - unique, hidden + b - unique
        for seg in segments:
            if seg["asset_id"] != aid:
                continue
            lo, hi = max(src_a, seg["source_in_ms"]), min(src_b, seg["source_out_ms"])
            if lo < hi:
                offset = seg["timeline_start_ms"] - seg["source_in_ms"]
                spans.append((lo + offset, hi + offset))
    return tuple(sorted(spans))


class Exporter:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.library = LibraryPaths.for_database(database.path)
        self.projects = ProjectService(database)

    # -- data ----------------------------------------------------------------------

    def _project(
        self, conn: sqlite3.Connection, project_id: str
    ) -> tuple[dict[str, Any], int, str]:
        state = self.projects._read(conn, project_id)
        row = conn.execute(
            "SELECT saved_at FROM editor_projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is not None:
            saved_at = row["saved_at"]
        else:
            story = conn.execute(
                "SELECT updated_at FROM stories WHERE id = ?", (project_id,)
            ).fetchone()
            saved_at = story["updated_at"]
        return state["document"], int(state["revision"]), saved_at

    def _events(
        self, conn: sqlite3.Connection, session_id: str, document: Mapping[str, Any] | None
    ) -> tuple[list[dict[str, Any]], list[MappedEvent], str]:
        """Event JSONL records and their project-timeline placement (read-only)."""
        key, _ = layout_info(conn, session_id)
        layout = session_layout(conn, session_id)
        segments = (
            document["project"]["tracks"][0]["segments"]
            if document and document["project"].get("tracks")
            else []
        )
        records, mapped = [], []
        for event in EventRepository(conn).list_for_session(session_id):
            observation = normalize(event)
            decision = conn.execute(
                "SELECT revision, decision_json FROM event_decisions WHERE event_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (observation["id"],),
            ).fetchone()
            effective = {
                "type": observation["type"],
                "start_ms": observation["start_ms"],
                "end_ms": observation["end_ms"],
                "review_state": observation["review_state"],
                "revision": 0,
            }
            if decision is not None:
                last = json.loads(decision["decision_json"])
                effective = {
                    "type": last["type"],
                    "start_ms": last["start_ms"],
                    "end_ms": last["end_ms"],
                    "review_state": last["state"],
                    "revision": decision["revision"],
                }
            snapshot = conn.execute(
                "SELECT layout_key FROM event_observations WHERE event_id = ?",
                (observation["id"],),
            ).fetchone()
            status = (
                "legacy"
                if snapshot is None or snapshot["layout_key"] is None
                else "current"
                if snapshot["layout_key"] == key
                else "stale"
            )
            spans = project_ranges(layout, segments, effective["start_ms"], effective["end_ms"])
            record: dict[str, Any] = {
                "record": "event",
                "schema_version": SCHEMA_VERSION,
                "observation": observation,
                "effective": effective,
                "status": status,
            }
            if document is not None:
                record["project_ranges"] = [{"start_ms": a, "end_ms": b} for a, b in spans]
            records.append(normalize(load("event-export", record)))
            if effective["review_state"] != "rejected" and spans:
                mapped.append(
                    MappedEvent(
                        observation["id"],
                        effective["type"],
                        effective["review_state"],
                        observation["confidence"],
                        effective["start_ms"],
                        effective["end_ms"],
                        spans,
                    )
                )
        mapped.sort(key=lambda e: (e.project_ranges[0], e.event_id))
        return records, mapped, key

    @staticmethod
    def _rate(conn: sqlite3.Connection, document: Mapping[str, Any]) -> float:
        """The first clip's frame rate, or the default when it is unknown."""
        tracks = document["project"].get("tracks") or []
        segments = tracks[0]["segments"] if tracks else []
        if not segments:
            return DEFAULT_RATE
        row = conn.execute(
            "SELECT fps_num, fps_den FROM media_assets WHERE id = ?", (segments[0]["asset_id"],)
        ).fetchone()
        if row is None or not row["fps_num"] or not row["fps_den"]:
            return DEFAULT_RATE
        return float(row["fps_num"]) / float(row["fps_den"])

    def _locations(
        self, conn: sqlite3.Connection, document: Mapping[str, Any]
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        locations: dict[str, str] = {}
        unavailable = 0
        for source in document["sources"]:
            if source.get("requires_relink"):
                continue
            try:
                path = readable_source(
                    self.library, AssetRepository(conn).location(source["asset_id"])
                )
            except NotFoundError:
                path = None
            if path is None:
                unavailable += 1
            else:
                locations[source["asset_id"]] = path.resolve().as_uri()
        warnings = (
            [
                {
                    "code": "export.paths_unavailable",
                    "detail": "Some source files cannot be found, so their locations are left out.",
                    "count": unavailable,
                }
            ]
            if unavailable
            else []
        )
        return locations, warnings

    # -- exports -------------------------------------------------------------------

    def project(self, project_id: str, fmt: str, *, include_paths: bool = False) -> dict[str, Any]:
        if fmt not in FORMATS:
            raise ExportFailed("export.unknown_format", "Choose a supported export format.")
        _, _, _, carries_paths = FORMATS[fmt]
        if include_paths and not carries_paths:
            raise ExportFailed(
                "export.paths_not_supported",
                "Only project, OTIO and FCPXML exports can include file locations.",
            )
        try:
            with contextlib.closing(self.database.connect()) as conn:
                conn.execute("BEGIN")
                try:
                    document, revision, saved_at = self._project(conn, project_id)
                    privacy_summary = PrivacyReviewService(self.database).require(
                        conn, project_id, document, revision
                    )
                    session_id = document["project"].get("session_id")
                    locations, path_warnings = (
                        self._locations(conn, document) if include_paths else ({}, [])
                    )
                    rate = self._rate(conn, document)
                    records: list[dict[str, Any]] = []
                    mapped: list[MappedEvent] = []
                    layout_key = None
                    if session_id and fmt in ("events", "csv", "otio", "fcpxml"):
                        records, mapped, layout_key = self._events(conn, session_id, document)
                finally:
                    conn.execute("ROLLBACK")
        except NotFoundError as exc:
            raise ExportFailed("export.not_found", "That project does not exist.", 404) from exc
        title = document["project"]["title"]
        paths = locations if include_paths else None
        try:
            if fmt == "project":
                doc, warnings = project_export(
                    document,
                    revision=revision,
                    saved_at=saved_at,
                    app_version=__version__,
                    schema_version=SCHEMA_VERSION,
                    locations=paths,
                )
                doc["extensions"]["privacy_review"] = privacy_summary
                content = canonical_json(normalize(load("project-export", doc)))
                capabilities = doc["capabilities"]
            elif fmt == "events":
                if not session_id or layout_key is None:
                    raise ExportFailed(
                        "export.no_session", "This project has no session, so it has no events."
                    )
                header = {
                    "record": "header",
                    "schema_version": SCHEMA_VERSION,
                    "format": EVENTS_FORMAT[0],
                    "format_version": EVENTS_FORMAT[1],
                    "generator": {"name": "openworld-moments", "version": __version__},
                    "session_id": session_id,
                    "project_id": project_id,
                    "layout_key": layout_key,
                    "event_count": len(records),
                    "extensions": {"privacy_review": privacy_summary},
                }
                load("event-export", header)
                content, warnings = events_jsonl(header, records), []
                capabilities = CAPABILITIES["events"]
            elif fmt in ("srt", "vtt"):
                project = document["project"]
                warnings = []
                if project.get("caption_settings"):
                    warnings.append(
                        {
                            "code": "export.caption_style_not_supported",
                            "detail": "Caption placement, style and burn-in are not part of "
                            "plain SRT/WebVTT; only text and timing are exported.",
                            "count": 1,
                        }
                    )
                if not project.get("captions"):
                    warnings.append(
                        {
                            "code": "export.no_captions",
                            "detail": "The project has no captions.",
                            "count": 1,
                        }
                    )
                content = captions_text(project.get("captions") or [], fmt)
                capabilities = CAPABILITIES[fmt]
            elif fmt == "csv":
                content, warnings = csv_markers(document, mapped)
                capabilities = CAPABILITIES["csv"]
            elif fmt == "otio":
                content, warnings = otio_timeline(
                    document, mapped, revision=revision, rate=rate, locations=paths
                )
                capabilities = CAPABILITIES["otio"] + (["source_paths"] if include_paths else [])
            else:
                content, warnings = fcpxml(document, mapped, locations=paths)
                capabilities = CAPABILITIES["fcpxml"] + (["source_paths"] if include_paths else [])
        except ExportError as exc:
            raise ExportFailed(exc.code, exc.message) from exc
        extension = FORMATS[fmt][0]
        result = _envelope(
            fmt,
            content,
            safe_filename(title, extension),
            [*warnings, *path_warnings],
            capabilities,
            bool(include_paths and paths),
        )

        result["privacy_review"] = privacy_summary
        return normalize(load("export-result", result))

    def render_manifest(self, render_id: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            row = conn.execute(
                "SELECT status, manifest_json FROM render_jobs WHERE id = ?", (render_id,)
            ).fetchone()
        if row is None:
            raise ExportFailed("render.not_found", "That render does not exist.", 404)
        if row["status"] != "ready" or row["manifest_json"] is None:
            raise ExportFailed(
                "export.manifest_unavailable",
                "Only completed renders have a manifest.",
                409,
            )
        manifest = normalize(load("export-manifest", json.loads(row["manifest_json"])))
        return _envelope(
            "manifest",
            canonical_json(manifest),
            f"{render_id}.manifest.json",
            [],
            CAPABILITIES["manifest"],
            False,
        )


def detector_versions(
    conn: sqlite3.Connection, session_id: str | None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Distinct detector and profile versions behind the session's current events.

    Only identifiers the manifest contract can name (slug + semantic version) are kept.
    """
    if not session_id:
        return [], []

    def nameable(entry: dict[str, str]) -> bool:
        return bool(_SLUG.fullmatch(entry["id"]) and _SEMVER.fullmatch(entry["version"]))

    detectors = [
        {"id": r[0], "version": r[1]}
        for r in conn.execute(
            "SELECT DISTINCT detector_id, detector_version FROM events WHERE session_id = ? "
            "AND detector_id IS NOT NULL ORDER BY detector_id, detector_version",
            (session_id,),
        )
    ]
    detectors = [d for d in detectors if nameable(d)]
    profiles = [
        {"id": r[0], "version": r[1]}
        for r in conn.execute(
            "SELECT DISTINCT profile_id, profile_version FROM events WHERE session_id = ? "
            "AND profile_id IS NOT NULL AND profile_version IS NOT NULL "
            "ORDER BY profile_id, profile_version",
            (session_id,),
        )
    ]
    return detectors, [p for p in profiles if nameable(p)]
