# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate, validate, cache, and clean up derived media (M08).

One ``proxy`` job prepares one asset's playback media: the proxy (when the
policy says it is needed), the filmstrip, and the waveform. Each artifact:

1. gets a recipe and cache key (``recipes``); a ready artifact with the same key
   whose file still exists is a cache hit and nothing runs,
2. is built in ``staging/derived/<job-id>/`` by FFmpeg (argument lists,
   ``-progress`` for the proxy, cancellable at any time),
3. is validated (FFprobe plus sampled decodes for the proxy; file checks for
   thumbnails and the waveform),
4. is moved into ``derived/<asset-id>/`` with one rename and recorded in
   ``derived_artifacts`` in one transaction; the previous artifact is removed
   after that.

Sources are only ever read. A cancelled or failed job leaves nothing in
``derived/``: its staging folder is removed.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import shutil
import sqlite3
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.media_asset_schema import MediaAsset

from openworld_moments.derived import recipes, waveform
from openworld_moments.derived.layout import (
    CleanupReport,
    DerivedPaths,
    fsync_file,
    replace_dir,
)
from openworld_moments.derived.policy import (
    ProxyDecision,
    ProxyPolicy,
    decide,
    display_size,
    proxy_geometry,
    thumbnail_size,
)
from openworld_moments.derived.tonemap import LUT_FILE, ToneMapSettings, lut
from openworld_moments.ingest.library import LibraryPaths, fsync_directory, readable_source
from openworld_moments.media.probe import ProbeCancelled, ProbeError, probe_file
from openworld_moments.media.process import (
    ToolCancelled,
    ToolNotStarted,
    ToolOutputTooLarge,
    ToolTimeout,
    run_tool,
)
from openworld_moments.media.tools import MediaTools, ToolInfo, list_codecs, list_filters
from openworld_moments.redaction import Redactor
from openworld_moments.storage import (
    AssetRepository,
    Database,
    DerivedArtifactRepository,
    DerivedArtifactRow,
    NotFoundError,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION

KINDS = ("proxy", "filmstrip", "waveform")
#: Share of the job's progress bar per artifact (only for artifacts that run).
WEIGHTS = {"proxy": 80, "filmstrip": 10, "waveform": 10}
PROGRESS_TOTAL = 1000
#: Duration tolerance between a proxy and its source.
DURATION_TOLERANCE_MS = 250
#: Sampled-decode checks (spec 13.4): proxy and source frames at these fractions.
SAMPLE_POINTS = (0.1, 0.5, 0.9)
MAX_LUMA_DIFF = 40  # SDR: mean luma of proxy vs source, 0-255
DARK, BRIGHT = 24, 235  # a frame darker / brighter than this is "black" / "white"
#: Free space kept in reserve on top of an artifact's estimated size.
SPACE_MARGIN = 64 * 1024 * 1024
PROXY_BITS_PER_SECOND = 6_000_000  # generous upper estimate for the proxy preset

Progress = Callable[[int, int, str], None]


class DerivedFailure(Exception):
    """An artifact could not be made. ``code`` is stable; ``message`` has no paths."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, str | int | float | bool | None] | None = None,
        stderr_tail: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details) if details else None
        self.stderr_tail = stderr_tail

    def error(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            error["details"] = self.details
        return error


class DerivedCancelled(Exception):
    pass


@dataclass(frozen=True)
class Plan:
    kind: str
    recipe: dict[str, Any]
    key: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _artifact_digest(path: Path) -> tuple[str, int]:
    """SHA-256 and size of a file, or of a folder (over its sorted names and file hashes)."""
    if path.is_file():
        return _sha256_file(path), path.stat().st_size
    digest = hashlib.sha256()
    size = 0
    for child in sorted(path.iterdir(), key=lambda p: p.name):
        digest.update(f"{child.name}\0{_sha256_file(child)}\n".encode())
        size += child.stat().st_size
    return digest.hexdigest(), size


class DerivedMedia:
    """Runs on job threads (generation) and API threads (status, cleanup)."""

    def __init__(
        self,
        database: Database,
        tools: MediaTools,
        *,
        library: LibraryPaths | None = None,
        probe_timeout_s: float = 60.0,
    ) -> None:
        self.database = database
        self.tools = tools
        self.library = library or LibraryPaths.for_database(database.path)
        self.paths = DerivedPaths(self.library.root)
        self.probe_timeout_s = probe_timeout_s
        # Held while an artifact is promoted and recorded, and during cleanup, so
        # cleanup never sees a promoted file before its row exists.
        self._lock = threading.Lock()
        self._capable: dict[str, list[str]] = {}

    # -- tools ------------------------------------------------------------------------

    def _tool(self, name: str) -> ToolInfo:
        tool = self.tools.tool(name)  # type: ignore[arg-type]
        if not tool.ok:
            raise DerivedFailure(
                f"tool.{name}_missing"
                if tool.status == "missing"
                else f"tool.{name}_{tool.status}",
                f"{'FFmpeg' if name == 'ffmpeg' else 'FFprobe'} is not usable: {tool.problem}. "
                "Install FFmpeg 6.0 or newer, or set OWM_FFMPEG / OWM_FFPROBE.",
                retryable=True,
            )
        return tool

    def missing_capabilities(self, ffmpeg: ToolInfo) -> list[str]:
        """Required encoders and filters this FFmpeg lacks (cached per build)."""
        key = f"{ffmpeg.path}|{ffmpeg.version}"
        if key not in self._capable:
            encoders = list_codecs(ffmpeg, "encoders")
            filters = list_filters(ffmpeg)
            missing = [f"encoder:{e}" for e in recipes.REQUIRED_ENCODERS if e not in encoders]
            missing += [f"filter:{f}" for f in recipes.REQUIRED_FILTERS if f not in filters]
            self._capable[key] = missing
        return self._capable[key]

    # -- planning ---------------------------------------------------------------------

    def _plans(
        self, asset: MediaAsset, decision: ProxyDecision, ffmpeg: ToolInfo
    ) -> dict[str, Plan]:
        """Recipe and cache key of every artifact that applies to the asset."""
        video = asset.video
        plans: dict[str, Plan] = {}
        if video is None:
            return plans
        audio = bool(asset.audio)
        geometry = proxy_geometry(video)
        if decision.needed:
            recipe = recipes.proxy_recipe(
                ffmpeg,
                geometry,
                audio=audio,
                source_range=video.color.range,
                tone_map=self._tone_map(asset),
            )
            plans["proxy"] = Plan("proxy", recipe, recipes.cache_key(asset.sha256, "proxy", recipe))
            source: dict[str, Any] = {"kind": "proxy", "cache_key": plans["proxy"].key}
            width, height = geometry.width, geometry.height
        else:
            source = {"kind": "original"}
            width, height = display_size(video)
        plan = recipes.filmstrip_plan(asset.duration_ms, *thumbnail_size(width, height))
        recipe = recipes.filmstrip_recipe(ffmpeg, plan, source)
        plans["filmstrip"] = Plan(
            "filmstrip", recipe, recipes.cache_key(asset.sha256, "filmstrip", recipe)
        )
        if audio:
            recipe = recipes.waveform_recipe(ffmpeg)
            plans["waveform"] = Plan(
                "waveform", recipe, recipes.cache_key(asset.sha256, "waveform", recipe)
            )
        return plans

    @staticmethod
    def _tone_map(asset: MediaAsset) -> ToneMapSettings | None:
        video = asset.video
        if video is None:
            return None
        transfer = proxy_geometry(video).hdr_transfer
        if transfer is None:
            return None
        return ToneMapSettings(transfer)  # type: ignore[arg-type]

    @staticmethod
    def _effective_policy(
        rows: Mapping[str, DerivedArtifactRow], requested: ProxyPolicy
    ) -> ProxyPolicy:
        """An asset that has a proxy keeps it current (and its thumbnails come from it),
        even when the policy alone would not ask for one."""
        proxy = rows.get("proxy")
        if requested == "auto" and proxy is not None and proxy.status == "ready":
            return "always"
        return requested

    def _present(self, row: DerivedArtifactRow) -> bool:
        if row.status != "ready" or row.relpath is None:
            return False
        path = self.paths.resolve(row.relpath)
        if path is None or path.is_symlink():
            return False
        return path.is_dir() if row.kind == "filmstrip" else path.is_file()

    # -- status -----------------------------------------------------------------------

    def status_doc(self, conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
        """The contract ``AssetDerivedMedia`` (raises NotFoundError)."""
        asset = AssetRepository(conn).get(asset_id)
        rows = DerivedArtifactRepository(conn).for_asset(asset_id)
        decision = decide(asset, self._effective_policy(rows, "auto"))
        ffmpeg = self.tools.tool("ffmpeg")
        plans = self._plans(asset, decision, ffmpeg) if ffmpeg.ok else None
        artifacts = []
        for kind in KINDS:
            artifacts.append(self._artifact_doc(kind, rows.get(kind), asset, decision, plans))
        doc = {
            "schema_version": SCHEMA_VERSION,
            "asset_id": asset_id,
            "proxy_decision": decision.doc(),
            "artifacts": artifacts,
        }
        return normalize(load("derived-media", doc))

    def _artifact_doc(
        self,
        kind: str,
        row: DerivedArtifactRow | None,
        asset: MediaAsset,
        decision: ProxyDecision,
        plans: dict[str, Plan] | None,
    ) -> dict[str, Any]:
        doc: dict[str, Any] = {"kind": kind}
        if row is None:
            if kind == "proxy" and not decision.needed:
                doc["status"] = "not_needed"
            elif kind == "waveform" and not asset.audio:
                doc["status"] = "not_applicable"
            else:
                doc["status"] = "not_generated"
            return doc
        doc["cache_key"] = row.cache_key
        if row.last_error is not None:
            doc["last_error"] = row.last_error
        if row.status == "failed":
            doc["status"] = "failed"
            return doc
        doc.update(
            {
                "path": row.relpath,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
                "created_at": row.created_at,
                "recipe": row.recipe,
                kind: row.info,
            }
        )
        current = plans.get(kind) if plans is not None else None
        if not self._present(row):
            doc["status"] = "missing"
        elif current is not None and current.key != row.cache_key:
            doc["status"] = "stale"
        else:
            doc["status"] = "ready"
        return doc

    # -- generation -------------------------------------------------------------------

    def generate(
        self,
        params: Mapping[str, Any],
        *,
        job_id: str,
        cancel: threading.Event,
        progress: Progress,
    ) -> dict[str, Any]:
        """The ``proxy`` job (contract DerivedMediaRequest → DerivedMediaResult)."""
        asset_id: str = params["asset_id"]
        policy: ProxyPolicy = params.get("proxy_policy", "auto")
        force = bool(params.get("force", False))
        requested = list(params.get("artifacts") or KINDS)
        ffmpeg = self._tool("ffmpeg")
        ffprobe = self._tool("ffprobe")
        missing = self.missing_capabilities(ffmpeg)
        if missing:
            raise DerivedFailure(
                "derived.ffmpeg_incapable",
                "This FFmpeg build lacks components derived media needs: "
                + ", ".join(missing)
                + ".",
                retryable=True,
                details={"missing": ", ".join(missing)},
            )
        with contextlib.closing(self.database.connect()) as conn:
            assets = AssetRepository(conn)
            try:
                asset = assets.get(asset_id)
                location = assets.location(asset_id)
            except NotFoundError as exc:
                raise DerivedFailure("asset.not_found", "The asset does not exist.") from exc
            source = readable_source(self.library, location)
            if source is None:
                raise DerivedFailure(
                    "derived.source_unavailable",
                    "The asset's file cannot be read right now (moved, deleted, or offline).",
                    retryable=True,
                )
            rows = DerivedArtifactRepository(conn).for_asset(asset_id)
            decision = decide(asset, self._effective_policy(rows, policy))
            plans = self._plans(asset, decision, ffmpeg)
            order = [k for k in KINDS if k in requested]
            if "filmstrip" in order and "proxy" in plans and "proxy" not in order:
                order.insert(0, "proxy")  # thumbnails are taken from the proxy
            runnable = [k for k in order if k in plans]
            spans = self._spans(runnable)
            outcomes: dict[str, str] = {}
            high_water = [0]  # progress never moves backwards
            self.paths.clean_staging(job_id)
            redactor = Redactor([str(source), str(self.library.root)])
            try:
                for kind in order:
                    plan = plans.get(kind)
                    if plan is None:
                        outcomes[kind] = "not_needed" if kind == "proxy" else "not_applicable"
                        continue
                    lo, hi = spans[kind]

                    def report(fraction: float, message: str, lo: int = lo, hi: int = hi) -> None:
                        done = lo + int((hi - lo) * max(0.0, min(1.0, fraction)))
                        high_water[0] = max(high_water[0], done)
                        progress(high_water[0], PROGRESS_TOTAL, message)

                    outcomes[kind] = self._artifact(
                        conn,
                        asset,
                        source,
                        plan,
                        plans,
                        force=force,
                        job_id=job_id,
                        tools=(ffmpeg, ffprobe),
                        cancel=cancel,
                        report=report,
                        redactor=redactor,
                    )
            finally:
                self.paths.clean_staging(job_id)
        progress(PROGRESS_TOTAL, PROGRESS_TOTAL, _summary(outcomes))
        return {"asset_id": asset_id, "proxy_decision": decision.doc(), "outcomes": outcomes}

    @staticmethod
    def _spans(kinds: list[str]) -> dict[str, tuple[int, int]]:
        total = sum(WEIGHTS[k] for k in kinds) or 1
        spans, start = {}, 0
        for kind in kinds:
            end = start + PROGRESS_TOTAL * WEIGHTS[kind] // total
            spans[kind] = (start, end)
            start = end
        return spans

    def _artifact(
        self,
        conn: sqlite3.Connection,
        asset: MediaAsset,
        source: Path,
        plan: Plan,
        plans: dict[str, Plan],
        *,
        force: bool,
        job_id: str,
        tools: tuple[ToolInfo, ToolInfo],
        cancel: threading.Event,
        report: Callable[[float, str], None],
        redactor: Redactor,
    ) -> str:
        repo = DerivedArtifactRepository(conn)
        previous = repo.get(asset.id, plan.kind)  # type: ignore[arg-type]
        if (
            not force
            and previous is not None
            and previous.cache_key == plan.key
            and self._present(previous)
        ):
            report(1.0, f"{plan.kind.capitalize()} is up to date")
            return "cached"
        staging = self.paths.job_staging(job_id) / plan.kind
        try:
            staging.mkdir(parents=True, exist_ok=True)
            self._check_space(asset, plan.kind)
            if plan.kind == "proxy":
                built, info = self._build_proxy(
                    asset, source, plan, staging, tools, cancel, report, redactor
                )
            elif plan.kind == "filmstrip":
                film_source = self._filmstrip_source(conn, asset, source, plans)
                built, info = self._build_filmstrip(
                    asset, film_source, plan, staging, tools[0], cancel, report, redactor
                )
            else:
                built, info = self._build_waveform(
                    asset, source, staging, tools[0], cancel, report, redactor
                )
            self._promote(conn, asset, plan, built, info, previous, job_id)
        except (ToolCancelled, ProbeCancelled, DerivedCancelled) as exc:
            raise DerivedCancelled from exc
        except DerivedFailure as exc:
            self._record_failure(conn, asset.id, plan, exc)
            raise
        except OSError as exc:
            failure = _os_failure(exc)
            self._record_failure(conn, asset.id, plan, failure)
            raise failure from exc
        return "generated"

    def _record_failure(
        self, conn: sqlite3.Connection, asset_id: str, plan: Plan, failure: DerivedFailure
    ) -> None:
        with contextlib.suppress(sqlite3.Error), transaction(conn):
            DerivedArtifactRepository(conn).record_failure(
                asset_id,
                plan.kind,  # type: ignore[arg-type]
                cache_key=plan.key,
                recipe=plan.recipe,
                error=failure.error(),
            )

    def _check_space(self, asset: MediaAsset, kind: str) -> None:
        estimate = SPACE_MARGIN
        if kind == "proxy":
            estimate += asset.duration_ms * PROXY_BITS_PER_SECOND // 8000
        try:
            free = shutil.disk_usage(self.library.root).free
        except OSError:
            return
        if free < estimate:
            raise DerivedFailure(
                "derived.disk_full",
                "There is not enough free space in the library folder for this artifact.",
                retryable=True,
                details={"required_bytes": estimate, "free_bytes": free},
            )

    def _filmstrip_source(
        self,
        conn: sqlite3.Connection,
        asset: MediaAsset,
        original: Path,
        plans: dict[str, Plan],
    ) -> Path:
        proxy_plan = plans.get("proxy")
        if proxy_plan is None:
            return original
        row = DerivedArtifactRepository(conn).get(asset.id, "proxy")
        if row is None or row.cache_key != proxy_plan.key or not self._present(row):
            raise DerivedFailure(
                "derived.proxy_required",
                "Thumbnails are taken from the proxy, which is not available.",
                retryable=True,
            )
        path = self.paths.resolve(row.relpath or "")
        if path is None:  # pragma: no cover - _present checked it
            raise DerivedFailure("derived.proxy_required", "The proxy path is invalid.")
        return path

    def _run(
        self,
        argv: list[str],
        *,
        timeout_s: float,
        cancel: threading.Event,
        redactor: Redactor,
        cwd: Path | None = None,
        on_stdout: Callable[[bytes], None] | None = None,
        max_stdout: int | None = None,
        what: str,
    ) -> bytes:
        kwargs: dict[str, Any] = {}
        if max_stdout is not None:
            kwargs["max_stdout"] = max_stdout
        try:
            result = run_tool(
                argv,
                timeout_s=timeout_s,
                cancel=cancel,
                redactor=redactor,
                cwd=cwd,
                on_stdout=on_stdout,
                **kwargs,
            )
        except ToolTimeout as exc:
            raise DerivedFailure(
                "derived.timeout",
                f"Creating the {what} did not finish within {timeout_s:g} seconds.",
                retryable=True,
                stderr_tail=exc.stderr_tail,
            ) from exc
        except ToolNotStarted as exc:
            raise DerivedFailure(
                "tool.ffmpeg_unusable", "FFmpeg could not be started.", retryable=True
            ) from exc
        except ToolOutputTooLarge as exc:
            raise DerivedFailure(
                "derived.ffmpeg_failed", f"FFmpeg produced unexpected output for the {what}."
            ) from exc
        if result.returncode != 0:
            tail = result.stderr_tail
            if "No space left" in tail or "ENOSPC" in tail or "Disk full" in tail:
                raise DerivedFailure(
                    "derived.disk_full",
                    "The disk ran out of space while writing the " + what + ".",
                    retryable=True,
                    stderr_tail=tail,
                )
            raise DerivedFailure(
                "derived.ffmpeg_failed",
                f"FFmpeg could not create the {what}.",
                details={"exit_code": result.returncode},
                stderr_tail=tail,
            )
        return result.stdout

    @staticmethod
    def _timeout(duration_ms: int, per_second: float) -> float:
        return 120.0 + duration_ms / 1000 * per_second

    # -- proxy ------------------------------------------------------------------------

    def _build_proxy(
        self,
        asset: MediaAsset,
        source: Path,
        plan: Plan,
        staging: Path,
        tools: tuple[ToolInfo, ToolInfo],
        cancel: threading.Event,
        report: Callable[[float, str], None],
        redactor: Redactor,
    ) -> tuple[Path, dict[str, Any]]:
        ffmpeg = tools[0]
        video = asset.video
        if video is None:  # pragma: no cover - planned only for video
            raise DerivedFailure("media.no_video_stream", "The asset has no video.")
        geometry = proxy_geometry(video)
        tone_map = self._tone_map(asset)
        if tone_map is not None:
            text, _ = lut(tone_map)
            (staging / LUT_FILE).write_text(text, "ascii")
        audio = bool(asset.audio)
        duration = max(1, asset.duration_ms)
        parser = _ProgressParser(lambda ms: report(ms / duration, "Creating proxy"))
        report(0.0, "Creating proxy")
        self._run(
            recipes.proxy_args(
                ffmpeg,
                source,
                geometry,
                audio=audio,
                source_range=video.color.range,
                tone_map=tone_map,
            ),
            timeout_s=self._timeout(duration, 10.0),
            cancel=cancel,
            redactor=redactor,
            cwd=staging,
            on_stdout=parser.feed,
            what="proxy",
        )
        built = staging / recipes.PROXY_OUTPUT
        report(0.97, "Checking proxy")
        probe = self._validate_proxy(asset, source, built, geometry, tools, cancel, redactor)
        info: dict[str, Any] = {
            "width": geometry.width,
            "height": geometry.height,
            "video_codec": "h264",
            "pixel_format": "yuv420p",
            "audio": audio,
            "duration_ms": probe["duration_ms"],
            "frame_rate": "source" if geometry.fps_cap is None else str(geometry.fps_cap),
            "tone_mapped": tone_map is not None,
        }
        if tone_map is not None:
            info["tone_map"] = tone_map.describe()
        return built, info

    def _validate_proxy(
        self,
        asset: MediaAsset,
        source: Path,
        built: Path,
        geometry: Any,
        tools: tuple[ToolInfo, ToolInfo],
        cancel: threading.Event,
        redactor: Redactor,
    ) -> dict[str, Any]:
        ffmpeg, ffprobe = tools
        try:
            probe = probe_file(built, ffprobe, timeout_s=self.probe_timeout_s, cancel=cancel)
        except ProbeError as exc:
            raise DerivedFailure(
                "derived.validation_failed",
                "The new proxy could not be read back.",
                details={"probe_error": exc.code},
            ) from exc
        video = probe.get("video") or {}
        problems: list[str] = []
        if video.get("codec") != "h264":
            problems.append("video codec")
        if video.get("pixel_format") not in ("yuv420p", None):
            problems.append("pixel format")
        if (video.get("width"), video.get("height")) != (geometry.width, geometry.height):
            problems.append("size")
        if video.get("rotation") not in (None, 0):
            problems.append("rotation")
        audio = probe.get("audio") or []
        if bool(audio) != bool(asset.audio):
            problems.append("audio presence")
        if audio and (audio[0].get("codec") != "aac" or audio[0].get("channels") != 2):
            problems.append("audio format")
        transfer = (video.get("color") or {}).get("transfer")
        if geometry.hdr_transfer is not None and transfer != "bt709":
            problems.append("tone-mapped transfer")
        tolerance = DURATION_TOLERANCE_MS
        rate = video.get("frame_rate")
        if rate:
            tolerance = max(tolerance, 3 * 1000 * rate["den"] // rate["num"])
        if abs(probe["duration_ms"] - asset.duration_ms) > tolerance:
            problems.append("duration")
        if problems:
            raise DerivedFailure(
                "derived.validation_failed",
                "The new proxy does not match its source: " + ", ".join(problems) + ".",
                details={"problems": ", ".join(problems)},
            )
        for fraction in SAMPLE_POINTS:
            at = int(asset.duration_ms * fraction)
            mine = self._luma(ffmpeg, built, at, cancel, redactor)
            theirs = self._luma(ffmpeg, source, at, cancel, redactor)
            if geometry.hdr_transfer is None and abs(mine - theirs) > MAX_LUMA_DIFF:
                problem = "brightness differs from the source"
            elif mine < DARK <= theirs:
                problem = "black frame where the source has picture"
            elif mine > BRIGHT >= theirs and geometry.hdr_transfer is None:
                problem = "white frame where the source has picture"
            else:
                continue
            raise DerivedFailure(
                "derived.validation_failed",
                f"A sampled proxy frame failed its check: {problem}.",
                details={
                    "at_ms": at,
                    "proxy_luma": round(mine, 1),
                    "source_luma": round(theirs, 1),
                },
            )
        return probe

    def _luma(
        self, ffmpeg: ToolInfo, path: Path, at_ms: int, cancel: threading.Event, redactor: Redactor
    ) -> float:
        data = self._run(
            recipes.luma_args(ffmpeg, path, at_ms),
            timeout_s=60.0,
            cancel=cancel,
            redactor=redactor,
            max_stdout=recipes.LUMA_W * recipes.LUMA_H * 2,
            what="validation sample",
        )
        if len(data) != recipes.LUMA_W * recipes.LUMA_H:
            raise DerivedFailure(
                "derived.validation_failed",
                "A sampled frame could not be decoded.",
                details={"at_ms": at_ms},
            )
        return sum(data) / len(data)

    # -- filmstrip --------------------------------------------------------------------

    def _build_filmstrip(
        self,
        asset: MediaAsset,
        source: Path,
        plan: Plan,
        staging: Path,
        ffmpeg: ToolInfo,
        cancel: threading.Event,
        report: Callable[[float, str], None],
        redactor: Redactor,
    ) -> tuple[Path, dict[str, Any]]:
        output = plan.recipe["output"]
        strip = recipes.filmstrip_plan(asset.duration_ms, output["width"], output["height"])
        folder = staging / recipes.FILMSTRIP_DIR
        folder.mkdir()
        report(0.0, "Creating thumbnails")
        self._run(
            recipes.filmstrip_args(ffmpeg, source, strip, asset.duration_ms),
            timeout_s=self._timeout(asset.duration_ms, 2.0),
            cancel=cancel,
            redactor=redactor,
            cwd=folder,
            what="thumbnails",
        )
        expected = [f"{i:04d}.jpg" for i in range(1, strip.count + 1)]
        found = sorted(p.name for p in folder.iterdir())
        bad = [n for n in expected if n in found and not _is_jpeg(folder / n)]
        if found != expected or bad:
            raise DerivedFailure(
                "derived.validation_failed",
                f"Expected {strip.count} thumbnails, found {len(found)} ({len(bad)} unreadable).",
                details={"expected": strip.count, "found": len(found)},
            )
        for name in expected:
            fsync_file(folder / name)
        report(1.0, "Thumbnails ready")
        info = {
            "count": strip.count,
            "width": strip.width,
            "height": strip.height,
            "format": "jpeg",
            "times_ms": list(strip.times_ms),
            "source": plan.recipe["source"]["kind"],
        }
        return folder, info

    # -- waveform ---------------------------------------------------------------------

    def _build_waveform(
        self,
        asset: MediaAsset,
        source: Path,
        staging: Path,
        ffmpeg: ToolInfo,
        cancel: threading.Event,
        report: Callable[[float, str], None],
        redactor: Redactor,
    ) -> tuple[Path, dict[str, Any]]:
        builder = waveform.WaveformBuilder()
        expected = max(1, asset.duration_ms * waveform.SAMPLE_RATE_HZ // 1000)

        def feed(block: bytes) -> None:
            builder.feed(block)
            report(builder.samples / expected, "Creating waveform")

        report(0.0, "Creating waveform")
        self._run(
            recipes.waveform_args(ffmpeg, source),
            timeout_s=self._timeout(asset.duration_ms, 1.0),
            cancel=cancel,
            redactor=redactor,
            on_stdout=feed,
            what="waveform",
        )
        if cancel.is_set():
            raise DerivedCancelled
        data = builder.finish()
        parsed = waveform.parse(data)
        if builder.samples == 0 or len(parsed.peaks) != waveform.expected_buckets(builder.samples):
            raise DerivedFailure(
                "derived.validation_failed", "The audio track produced no waveform samples."
            )
        built = staging / recipes.WAVEFORM_OUTPUT
        built.write_bytes(data)
        fsync_file(built)
        info = {
            "format": "owm-waveform",
            "format_version": waveform.FORMAT_VERSION,
            "buckets_per_second": waveform.BUCKETS_PER_SECOND,
            "sample_rate_hz": waveform.SAMPLE_RATE_HZ,
            "bucket_count": len(parsed.peaks),
        }
        return built, info

    # -- promotion --------------------------------------------------------------------

    def _promote(
        self,
        conn: sqlite3.Connection,
        asset: MediaAsset,
        plan: Plan,
        built: Path,
        info: dict[str, Any],
        previous: DerivedArtifactRow | None,
        job_id: str,
    ) -> None:
        relpath = self.paths.relpath(asset.id, plan.kind, plan.key)
        target = self.paths.resolve(relpath)
        if target is None:  # pragma: no cover - relpath() builds valid paths
            raise DerivedFailure("derived.invalid_path", "Invalid artifact path.")
        sha256, size = _artifact_digest(built)
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            if built.is_dir():
                trash = target.parent / f".{target.name}.replaced-{job_id}"
                replace_dir(built, target, trash, inside=self.paths.derived)
            else:
                fsync_file(built)
                promote_file(built, target)
            fsync_directory(target.parent)
            now = utc_now()
            with transaction(conn):
                DerivedArtifactRepository(conn).put(
                    DerivedArtifactRow(
                        asset_id=asset.id,
                        kind=plan.kind,  # type: ignore[arg-type]
                        status="ready",
                        cache_key=plan.key,
                        recipe=plan.recipe,
                        info=info,
                        relpath=relpath,
                        size_bytes=size,
                        sha256=sha256,
                        created_at=now,
                        updated_at=now,
                    )
                )
            if previous is not None and previous.relpath and previous.relpath != relpath:
                self.paths.remove_artifact(previous.relpath)

    # -- cleanup ----------------------------------------------------------------------

    def cleanup(self) -> dict[str, int]:
        """Remove derived files no row points at (contract DerivedCleanupResult)."""
        with self._lock, contextlib.closing(self.database.connect()) as conn:
            keep = DerivedArtifactRepository(conn).relpaths()
            asset_ids = AssetRepository(conn).ids()
            report: CleanupReport = self.paths.cleanup(keep, asset_ids)
        return report.doc()


def promote_file(built: Path, target: Path) -> None:
    """Move a finished file into place (one rename on the same volume). Separate so
    tests can simulate a failing write."""
    os.replace(built, target)


def _is_jpeg(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(3)
    except OSError:
        return False
    return head == b"\xff\xd8\xff" and path.stat().st_size > 100


def _os_failure(exc: OSError) -> DerivedFailure:
    if exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
        return DerivedFailure(
            "derived.disk_full",
            "The disk ran out of space while writing derived media.",
            retryable=True,
        )
    return DerivedFailure(
        "derived.write_failed",
        f"Derived media could not be written: {exc.strerror or 'I/O error'}.",
        retryable=True,
    )


def _summary(outcomes: Mapping[str, str]) -> str:
    labels = {
        "generated": "created",
        "cached": "up to date",
        "not_needed": "not needed",
        "not_applicable": "not applicable",
    }
    return ", ".join(f"{k} {labels.get(v, v)}" for k, v in outcomes.items()) or "Nothing to do"


class _ProgressParser:
    """Reads FFmpeg ``-progress`` output (``key=value`` lines) and reports out_time."""

    def __init__(self, on_time_ms: Callable[[int], None]) -> None:
        self._on_time_ms = on_time_ms
        self._buffer = b""

    def feed(self, block: bytes) -> None:
        self._buffer += block
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            key, _, value = line.strip().partition(b"=")
            # out_time_us (and the misnamed out_time_ms) are microseconds.
            if key in (b"out_time_us", b"out_time_ms") and value.isdigit():
                self._on_time_ms(int(value) // 1000)
