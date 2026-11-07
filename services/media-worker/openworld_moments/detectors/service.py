# SPDX-License-Identifier: AGPL-3.0-or-later
"""Versioned built-in detector orchestration; one atomic result per clip/detector."""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments.derived.service import DerivedCancelled, DerivedMedia
from openworld_moments.detectors.audio import AudioFeatures
from openworld_moments.detectors.audio_input import (
    AUDIO_SAMPLER_VERSION,
    decode_audio,
    track_policy,
)
from openworld_moments.detectors.calibration import Calibration
from openworld_moments.detectors.example import BrightRegion
from openworld_moments.detectors.inputs import (
    OCR_SAMPLER_VERSION,
    OCR_SIZE,
    ROI_SAMPLER_VERSION,
    SAMPLER_VERSION,
    content_hash,
    decode_frames,
    decode_region,
    require_roi_detail,
    require_text_detail,
)
from openworld_moments.detectors.profiles import (
    ProfileCatalog,
    ResolvedProfile,
    canonical,
    compatibility,
    digest,
)
from openworld_moments.detectors.sdk import (
    SDK_VERSION,
    AnalysisCancelled,
    AnalysisContext,
    AnalysisError,
    AudioSamples,
    Detection,
    Detector,
    checkpoint,
)
from openworld_moments.detectors.text import SubtitleDetector, TextDetector
from openworld_moments.detectors.wanted import WantedState
from openworld_moments.ids import new_id
from openworld_moments.media.process import ToolCancelled
from openworld_moments.media.tools import MediaTools
from openworld_moments.storage import (
    AssetRepository,
    Database,
    DerivedArtifactRepository,
    EventRepository,
    SessionRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

Progress = Callable[[int, int, str], None]
Registry = Mapping[str, Callable[[], Detector]]
BUILTINS: Registry = MappingProxyType(
    {
        BrightRegion.id: BrightRegion,
        WantedState.id: WantedState,
        TextDetector.id: TextDetector,
        SubtitleDetector.id: SubtitleDetector,
        AudioFeatures.id: AudioFeatures,
    }
)
MAX_EVENTS = 10_000


def _plain(value: Any) -> Any:
    """Copy nested immutable SDK evidence into JSON data before schema validation."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


class Analyzer:
    def __init__(
        self,
        database: Database,
        tools: MediaTools,
        derived: DerivedMedia,
        *,
        catalog: ProfileCatalog | None = None,
        registry: Registry = BUILTINS,
    ) -> None:
        self.database, self.tools, self.derived = database, tools, derived
        self.catalog = catalog or ProfileCatalog()
        self.registry: Registry = MappingProxyType(dict(registry))

    def profile(self, profile_id: str) -> ResolvedProfile:
        profile = Calibration(self.database, self.catalog).effective(profile_id)
        for index, setting in enumerate(profile.document()["detectors"]):
            if setting["enabled"] and setting["id"] not in self.registry:
                raise AnalysisError(
                    "profile.invalid", f"detectors[{index}].id: unknown built-in detector"
                )
        return profile

    def run(
        self,
        params: Mapping[str, Any],
        *,
        job_id: str,
        cancel: threading.Event | None = None,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        cancel = cancel or threading.Event()
        report = progress or (lambda *_: None)
        checkpoint(cancel)
        resolved = self.profile(params["profile_id"])
        profile = resolved.document()
        settings = [s for s in profile["detectors"] if s["enabled"]]
        outcomes: list[dict[str, Any]] = []
        sid: str = params["session_id"]
        with contextlib.closing(self.database.connect()) as conn:
            repo = SessionRepository(conn)
            repo.get(sid)
            links = repo.assets(sid)
            layout = self._layout(conn, sid)
            total = max(1, len(links) * len(settings))
            report(0, total * 100, "Preparing detector analysis")
            virtual_start = 0
            for index, link in enumerate(links):
                hidden = (link.overlap_with_previous_ms or 0) if index else 0
                asset = AssetRepository(conn).get(link.asset_id)
                # Reject incompatibility for each clip without discarding other clips.
                prepared: tuple[Path, str, dict[str, str]] | None = None
                frames = None
                frames_key = ""
                audio: AudioSamples | None = None
                audio_ready = False
                for setting in settings:
                    context = None
                    checkpoint(cancel)
                    outcome: dict[str, Any] = {
                        "asset_id": link.asset_id,
                        "detector_id": setting["id"],
                        "event_ids": [],
                    }
                    ordinal = len(outcomes)
                    try:
                        detector = self.registry[setting["id"]]()
                        video = asset.video
                        if video is None:
                            raise AnalysisError("profile.incompatible", "frame: asset has no video")
                        width, height = video.width, video.height
                        if video.rotation in (90, 270):
                            width, height = height, width
                        locale = params.get("locale") or setting.get("locale")
                        hears = "audio.pcm" in detector.capabilities
                        if detector.capabilities != {"audio.pcm"}:
                            # Picture geometry does not constrain audio-only detectors.
                            compatibility(profile, width, height, locale)
                        if not detector.capabilities <= set(profile["capabilities"]):
                            raise AnalysisError(
                                "profile.incompatible",
                                "capabilities: detector requirements are unavailable",
                            )
                        if not detector.required_regions <= profile["regions"].keys():
                            raise AnalysisError(
                                "profile.incompatible", "regions: detector region is unavailable"
                            )
                        if detector.id != setting["id"] or not re.fullmatch(
                            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?",
                            detector.version,
                        ):
                            raise AnalysisError(
                                "analysis.invalid_detector", "Detector identity/version is invalid."
                            )
                        extra_versions = {}
                        if isinstance(detector, TextDetector):
                            extra_versions = detector.configure(
                                setting, profile.get("locales", {}).get(locale, {}), cancel
                            )
                            extra_versions["ocr_locale"] = locale
                        if prepared is None:
                            prepared = self._prepare(conn, link.asset_id, job_id, cancel)
                        path, input_key, base_versions = prepared
                        versions = dict(base_versions)
                        versions.update(extra_versions)
                        sample_region = getattr(detector, "sample_region", None)
                        dimensions = getattr(detector, "sample_dimensions", (200, 40))
                        roi = tuple(profile["regions"][sample_region]) if sample_region else None
                        sample_key = canonical([roi, dimensions])
                        if hears:
                            versions["sampler"] = AUDIO_SAMPLER_VERSION
                            versions["audio_track"] = track_policy(len(asset.audio or []))
                        if roi is not None:
                            if dimensions == OCR_SIZE:
                                versions["sampler"] = OCR_SAMPLER_VERSION
                                require_text_detail(width, height, roi)
                            else:
                                versions["sampler"] = ROI_SAMPLER_VERSION
                                require_roi_detail(
                                    width,
                                    height,
                                    roi,
                                    setting.get("wanted", {}).get("max_level", 5),
                                )
                        key = digest(
                            [
                                resolved.key,
                                setting,
                                locale,
                                detector.id,
                                detector.version,
                                input_key,
                                versions,
                                layout,
                                link.asset_id,
                            ]
                        )
                        cached = self._cached(conn, sid, link.asset_id, detector.id, key)
                        if cached is not None and not params.get("force", False):
                            outcome.update(status="cached", event_ids=cached)
                        else:
                            if hears:
                                if not audio_ready:
                                    # The first audio stream, like the proxy; none → no events.
                                    audio = (
                                        decode_audio(path, self.tools.tool("ffmpeg"), cancel)
                                        if asset.audio
                                        else None
                                    )
                                    audio_ready = True
                            elif frames is None or frames_key != sample_key:
                                frames = None
                                frames = (
                                    (
                                        decode_region(
                                            path, self.tools.tool("ffmpeg"), cancel, roi, dimensions
                                        )
                                        if dimensions == OCR_SIZE
                                        else decode_region(
                                            path, self.tools.tool("ffmpeg"), cancel, roi
                                        )
                                    )
                                    if roi is not None
                                    else decode_frames(path, self.tools.tool("ffmpeg"), cancel)
                                )
                                frames_key = sample_key

                            def frame_progress(done: int, count: int, unit: int = ordinal) -> None:
                                report(
                                    unit * 100 + min(99, done * 100 // max(1, count)),
                                    total * 100,
                                    "Analyzing clip",
                                )

                            context = AnalysisContext(
                                link.asset_id,
                                asset.duration_ms,
                                () if hears else (frames or ()),
                                MappingProxyType(
                                    {k: tuple(v) for k, v in profile["regions"].items()}
                                ),
                                MappingProxyType(dict(setting)),
                                MappingProxyType(
                                    {
                                        k: tuple(v)
                                        for k, v in profile.get("locales", {})
                                        .get(locale, {})
                                        .get("vocabulary", {})
                                        .items()
                                    }
                                ),
                                lambda: checkpoint(cancel),
                                frame_progress,
                                audio if hears else None,
                            )
                            docs: list[dict[str, Any]] = []
                            try:
                                detector.setup(context)
                                for finding in detector.detect(context):
                                    checkpoint(cancel)
                                    if len(docs) >= MAX_EVENTS:
                                        raise AnalysisError(
                                            "analysis.too_many_events",
                                            "Detector exceeded the event limit.",
                                        )
                                    doc = self._event(
                                        finding,
                                        sid,
                                        link.asset_id,
                                        detector,
                                        profile,
                                        versions,
                                        key,
                                        hidden,
                                        virtual_start,
                                        asset.duration_ms,
                                        setting.get("min_confidence", 0),
                                    )
                                    if doc is not None:
                                        docs.append(doc)
                            finally:
                                detector.close()
                            checkpoint(cancel)
                            with transaction(conn):
                                # A correction during analysis must not commit obsolete timing.
                                current = self._layout(conn, sid)
                                if current != layout:
                                    raise AnalysisError(
                                        "analysis.session_changed",
                                        "Session layout changed; analyze again.",
                                    )
                                self._save(conn, sid, link.asset_id, detector.id, key, docs)
                            outcome.update(status="computed", event_ids=[d["id"] for d in docs])
                    except (AnalysisCancelled, ToolCancelled, DerivedCancelled) as exc:
                        raise AnalysisCancelled from exc
                    except Exception as exc:
                        # Detector errors may contain arbitrary filenames/transcripts. Never
                        # expose exception text. Known application errors are already safe.
                        code = (
                            exc.code
                            if isinstance(exc, AnalysisError)
                            else "analysis.detector_failed"
                        )
                        message = (
                            exc.message
                            if isinstance(exc, AnalysisError)
                            else "Detector analysis failed; other results are kept."
                        )
                        outcome.update(
                            status="skipped"
                            if code in ("profile.incompatible", "ocr.unavailable")
                            else "failed",
                            error={"code": code, "message": message, "retryable": True},
                        )
                    outcomes.append(outcome)
                    report(len(outcomes) * 100, total * 100, "Detector result recorded")
                virtual_start += max(0, asset.duration_ms - hidden)
        checkpoint(cancel)
        report(total * 100, total * 100, "Detector analysis finished")
        return normalize(
            load(
                "analysis",
                {
                    "schema_version": SCHEMA_VERSION,
                    "session_id": sid,
                    "profile_id": profile["id"],
                    "outcomes": outcomes,
                },
            )
        )

    @staticmethod
    def _layout(conn: sqlite3.Connection, sid: str) -> list[tuple[str, int, int]]:
        return [
            (r[0], r[1], r[2])
            for r in conn.execute(
                "SELECT sa.asset_id, a.duration_ms, sa.overlap_with_previous_ms "
                "FROM session_assets sa JOIN media_assets a ON a.id=sa.asset_id "
                "WHERE sa.session_id=? ORDER BY sa.order_index",
                (sid,),
            )
        ]

    def checked_proxy(
        self, conn: sqlite3.Connection, asset_id: str, job_id: str, cancel: threading.Event
    ) -> tuple[Path, str]:
        """A current derived proxy whose bytes match its row, and its input key. Shared
        with transcription (M18) so no producer ever reads an original."""
        path, key, _ = self._prepare(conn, asset_id, job_id, cancel)
        return path, key

    @staticmethod
    def layout(conn: sqlite3.Connection, sid: str) -> list[tuple[str, int, int]]:
        return Analyzer._layout(conn, sid)

    def _prepare(
        self, conn: sqlite3.Connection, asset_id: str, job_id: str, cancel: threading.Event
    ) -> tuple[Path, str, dict[str, str]]:
        self.derived.generate(
            {"asset_id": asset_id, "artifacts": ["proxy"], "proxy_policy": "always"},
            job_id=job_id,
            cancel=cancel,
            progress=lambda *_: None,
        )
        row = DerivedArtifactRepository(conn).get(asset_id, "proxy")
        if row is None or row.relpath is None:
            raise AnalysisError("analysis.input_missing", "A current derived proxy is required.")
        path = self.derived.paths.resolve(row.relpath)
        if (
            path is None
            or path.is_symlink()
            or not path.resolve().is_relative_to(self.derived.paths.derived.resolve())
        ):
            raise AnalysisError("analysis.input_invalid", "The derived input path is invalid.")
        actual = content_hash(path, cancel)
        if actual != row.sha256:
            raise AnalysisError(
                "analysis.input_changed", "Derived bytes changed; rebuild playback media."
            )
        tool = self.tools.tool("ffmpeg")
        versions = {
            "sdk": SDK_VERSION,
            "sampler": SAMPLER_VERSION,
            "ffmpeg": tool.version or "unknown",
        }
        return path, digest([row.cache_key, actual]), versions

    @staticmethod
    def _event(
        finding: Detection,
        sid: str,
        aid: str,
        detector: Detector,
        profile: dict[str, Any],
        versions: dict[str, str],
        key: str,
        hidden: int,
        start: int,
        duration: int,
        minimum: float,
    ) -> dict[str, Any] | None:
        if not 0 <= finding.start_ms < finding.end_ms <= duration:
            raise AnalysisError(
                "analysis.invalid_event", "Detector emitted an out-of-source interval."
            )
        source = {
            "kind": "detector",
            "detector_id": detector.id,
            "detector_version": detector.version,
            "profile_id": profile["id"],
            "profile_version": profile["profile_version"],
            "tool_versions": versions,
            "input_key": key,
        }
        # Validate even events that will be hidden or filtered. Invalid output never succeeds.
        raw = {
            "schema_version": SCHEMA_VERSION,
            "id": new_id("evt"),
            "session_id": sid,
            "asset_id": aid,
            "type": finding.type,
            "start_ms": finding.start_ms,
            "end_ms": finding.end_ms,
            "confidence": finding.confidence,
            "attributes": dict(finding.attributes),
            "evidence": json.loads(canonical(_plain(finding.evidence))),
            "source": source,
            "review_state": "unreviewed",
        }
        load("event", raw)
        if finding.end_ms <= hidden or finding.confidence < minimum:
            return None
        raw["start_ms"] = start + max(hidden, finding.start_ms) - hidden
        raw["end_ms"] = start + finding.end_ms - hidden
        raw["attributes"].update(source_start_ms=finding.start_ms, source_end_ms=finding.end_ms)
        return normalize(load("event", raw))

    @staticmethod
    def _cached(
        conn: sqlite3.Connection, sid: str, aid: str, detector: str, key: str
    ) -> list[str] | None:
        row = conn.execute(
            "SELECT event_ids_json FROM detector_runs WHERE session_id=? "
            "AND asset_id=? AND detector_id=? AND cache_key=?",
            (sid, aid, detector, key),
        ).fetchone()
        if row is None:
            return None
        ids: list[str] = json.loads(row[0])
        repo = EventRepository(conn)
        for event_id in ids:
            if conn.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
                return None
            repo.get(event_id)
        return ids

    @staticmethod
    def _save(
        conn: sqlite3.Connection,
        sid: str,
        aid: str,
        detector: str,
        key: str,
        docs: list[dict[str, Any]],
    ) -> None:
        # Replace only this producer's unreviewed records. Reviewed/user events survive.
        conn.execute(
            "DELETE FROM events WHERE session_id=? AND asset_id=? AND detector_id=? "
            "AND source_kind='detector' AND review_state='unreviewed'",
            (sid, aid, detector),
        )
        for doc in docs:
            EventRepository(conn).add(load("event", doc))  # type: ignore[arg-type]
        conn.execute(
            "INSERT INTO detector_runs VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id,asset_id,detector_id) DO UPDATE SET "
            "cache_key=excluded.cache_key,event_ids_json=excluded.event_ids_json,"
            "computed_at=excluded.computed_at",
            (sid, aid, detector, key, canonical([d["id"] for d in docs]), utc_now()),
        )
