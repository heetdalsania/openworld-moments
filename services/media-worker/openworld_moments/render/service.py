# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render a project revision to a validated MP4 (M24).

1. Read the committed editor document; refuse missing, mismatched or unlinked sources.
2. Hash every referenced original and compare it with the project's source identity.
3. Build the plan (IR) for the preset and an encoder that passed a real test encode.
4. Check free space, then encode into an owned staging folder with progress.
5. Validate the output (FFprobe audit, sampled decodes, black frames).
6. Write the export manifest, move both into ``<library>/renders/<project>/`` and only
   then mark the record ``ready``. Cancellation and failures never leave a complete file.
A hardware encoder failure ends with an explicit CPU-fallback offer, never a silent switch.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments import __version__
from openworld_moments.derived.policy import display_size, proxy_geometry
from openworld_moments.derived.tonemap import ToneMapSettings, lut
from openworld_moments.detectors.calibration import Calibration
from openworld_moments.detectors.inputs import content_hash
from openworld_moments.detectors.profiles import ProfileError
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.exports.formats import canonical_json
from openworld_moments.exports.service import detector_versions
from openworld_moments.ingest.library import LibraryPaths, readable_source
from openworld_moments.media.process import ToolCancelled, ToolError, run_tool
from openworld_moments.media.tools import MediaTools
from openworld_moments.privacy.service import PrivacyError, PrivacyReviewService
from openworld_moments.projects.service import ProjectError, ProjectService
from openworld_moments.redaction import Redactor
from openworld_moments.render.encoders import CPU, ENCODERS, EncoderProbe, EncoderSpec
from openworld_moments.render.plan import (
    LUT_NAMES,
    RenderError,
    SourceFacts,
    build_plan,
    materialize,
)
from openworld_moments.render.presets import PresetCatalog
from openworld_moments.render.validate import validate_output
from openworld_moments.storage import AssetRepository, Database, NotFoundError, transaction, utc_now
from openworld_moments.storage.repositories import SCHEMA_VERSION

Progress = Callable[[int, int, str], None]
STAGING = Path("staging") / "renders"
RENDERS = Path("renders")
#: Free space kept in reserve beyond the estimated output size.
DISK_RESERVE = 64 * 1024 * 1024
#: How long to keep retrying removal of a staging folder that is still in use.
REMOVE_RETRY_S = 5.0


def remove_tree(path: Path, retry_s: float = REMOVE_RETRY_S) -> bool:
    """Delete an owned folder, retrying while files in it are still locked.

    On Windows a just-killed FFmpeg, or an antivirus scan of the file it wrote, can
    keep a handle open for a moment after the process exits, and deleting then fails.
    Returns whether the folder is gone; leftovers are removed at worker startup.
    """
    deadline = time.monotonic() + retry_s
    while True:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return not path.exists()
            time.sleep(0.1)
        else:
            return True


STORED_COLUMNS = frozenset(
    {
        "status",
        "progress",
        "finished_at",
        "project_revision",
        "output_path",
        "manifest_path",
        "plan_json",
        "validation_json",
        "output_json",
        "error_json",
        "fallback_json",
        "manifest_json",
    }
)


class RenderCancelled(Exception):
    pass


class RenderFailed(Exception):
    """A render that ended unsuccessfully, with its stored record."""

    def __init__(self, error: RenderError, record: dict[str, Any]) -> None:
        super().__init__(error.message)
        self.error, self.record = error, record


def estimate_bytes(plan: dict[str, Any]) -> int:
    """A conservative output-size estimate for the free-space preflight."""
    seconds = plan["duration_ms"] / 1000
    video = plan["preset"]["video"]
    out = plan["output"]
    if "bitrate_kbps" in video:
        video_bps = video["bitrate_kbps"] * 1000
    else:  # about 0.15 bits per pixel per frame at CRF 18-23; generous on purpose
        video_bps = out["width"] * out["height"] * out["fps"]["num"] / out["fps"]["den"] * 0.15
    audio_bps = plan["preset"]["audio"]["bitrate_kbps"] * 1000 if out["audio"] else 0
    return int(seconds * (video_bps + audio_bps) / 8 * 1.25)


def failure_from_stderr(stderr: str, encoder: EncoderSpec) -> RenderError:
    text = stderr.lower()
    if "no space left" in text or "disk full" in text:
        return RenderError(
            "render.disk_full", "The library drive ran out of space while rendering."
        )
    if encoder.kind == "hardware":
        return RenderError(
            "render.hardware_encoder_failed",
            f"{encoder.label} stopped during encoding. You can render with the CPU encoder "
            "instead; it uses the preset's own quality settings.",
            details={"fallback_encoder": CPU.id},
        )
    return RenderError("render.encode_failed", "FFmpeg could not render this project.")


class Renderer:
    def __init__(
        self,
        database: Database,
        tools: MediaTools,
        *,
        presets: PresetCatalog | None = None,
        probe: EncoderProbe | None = None,
        encoders: Mapping[str, EncoderSpec] | None = None,
        calibration: Calibration | None = None,
    ) -> None:
        self.database, self.tools = database, tools
        self.library = LibraryPaths.for_database(database.path)
        self.root = self.library.root
        self.projects = ProjectService(database)
        self.presets = presets or PresetCatalog()
        self.encoders = dict(encoders or ENCODERS)
        self.probe = probe or EncoderProbe(self.encoders)
        self.calibration = calibration or Calibration(database)

    # -- catalog and status ----------------------------------------------------------

    def encoder_status(self, *, refresh: bool = False) -> dict[str, Any]:
        tool = self.tools.tool("ffmpeg")
        return normalize(
            load(
                "render-encoders",
                {
                    "schema_version": SCHEMA_VERSION,
                    "ffmpeg_version": tool.version or "unknown",
                    "encoders": self.probe.status(tool, refresh=refresh),
                },
            )
        )

    def _encoder(self, encoder_id: str) -> EncoderSpec:
        spec = self.encoders.get(encoder_id)
        if spec is None:
            raise RenderError("render.unknown_encoder", "That encoder is not supported.")
        if spec.kind == "hardware":
            status = {e["id"]: e for e in self.encoder_status()["encoders"]}.get(spec.id)
            if status is None or not status["available"]:
                raise RenderError(
                    "render.encoder_unavailable",
                    (status or {}).get("reason", "That encoder is not available here."),
                )
        return spec

    def clean_staging(self) -> None:
        """Remove partial renders left by a crash. Only when no render runs."""
        target = self.root / STAGING
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)

    def check_request(self, params: Mapping[str, Any]) -> None:
        """Refuse a render up front when the project, preset or encoder cannot work."""
        state = self._project(params["project_id"])
        self._check_revision(state, params)
        self._privacy(state)
        self.presets.get(params["preset_id"])
        encoder = self._encoder(params.get("encoder", CPU.id))
        self._check_sources(state)
        facts = {}
        used = {
            s["asset_id"] for t in state["document"]["project"]["tracks"] for s in t["segments"]
        }
        with contextlib.closing(self.database.connect()) as conn:
            for source in state["document"]["sources"]:
                if source["asset_id"] not in used:
                    continue
                asset = AssetRepository(conn).get(source["asset_id"])
                video = asset.video
                w, h = display_size(video) if video else (1920, 1080)
                facts[source["asset_id"]] = SourceFacts(
                    source["asset_id"],
                    source["sha256"],
                    source["original_name"],
                    bool(asset.audio),
                    None,
                    None,
                    w,
                    h,
                )
        build_plan(
            state["document"],
            facts,
            self.presets.get(params["preset_id"]),
            encoder,
            ffmpeg_version="check",
            omit_text=bool(params.get("omit_text", False)),
            layout_profile=self._layout_profile(state["document"]),
            review_layout=bool(params.get("review_layout", False)),
        )

    def _privacy(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            with contextlib.closing(self.database.connect()) as conn:
                conn.execute("BEGIN")
                saved = self.projects._read(conn, state["document"]["project"]["id"])
                if saved["revision"] != state["revision"] or saved["document"] != state["document"]:
                    raise RenderError(
                        "render.revision_changed",
                        "The saved project changed. Review it again before rendering.",
                    )
                return PrivacyReviewService(self.database).require(
                    conn, state["document"]["project"]["id"], state["document"], state["revision"]
                )
        except PrivacyError as exc:
            raise RenderError(exc.code, exc.message, status=exc.status) from exc

    @staticmethod
    def _check_revision(state: dict[str, Any], params: Mapping[str, Any]) -> None:
        if "expected_revision" in params and state["revision"] != params["expected_revision"]:
            raise RenderError(
                "render.revision_changed",
                "The project changed after review. "
                "Review the current saved revision before rendering.",
            )

    def _layout_profile(self, document: dict[str, Any]) -> dict[str, Any] | None:
        layout = document["layout"]
        if not layout.get("profile_id"):
            return None
        try:
            state = self.calibration.state(layout["profile_id"])
            profile = state["effective"]
            if (
                state["base_changed"]
                or state["conflict"]
                or profile["profile_version"] != layout["profile_version"]
            ):
                return None
            return dict(profile)
        except ProfileError:
            return None

    # -- records ---------------------------------------------------------------------

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": row["id"],
            "project_id": row["story_id"],
            "status": row["status"],
            "preset_id": row["preset_id"],
            "encoder": row["encoder"] or CPU.id,
            "created_at": row["created_at"],
            "progress": row["progress"],
        }
        if row["project_revision"] is not None:
            doc["project_revision"] = row["project_revision"]
        for key, column in (
            ("plan", "plan_json"),
            ("validation", "validation_json"),
            ("output", "output_json"),
            ("error", "error_json"),
            ("fallback", "fallback_json"),
        ):
            if row[column]:
                doc[key] = json.loads(row[column])
        if row["finished_at"]:
            doc["finished_at"] = row["finished_at"]
        return normalize(load("render", doc))

    def get(self, render_id: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM render_jobs WHERE id=?", (render_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"render {render_id} not found")
        return self._record(row)

    def for_project(self, project_id: str) -> list[dict[str, Any]]:
        with contextlib.closing(self.database.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM render_jobs WHERE story_id=? AND encoder IS NOT NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 100",
                (project_id,),
            ).fetchall()
        return [self._record(r) for r in rows]

    def _store(self, render_id: str, **fields: Any) -> None:
        columns = {
            "plan": "plan_json",
            "validation": "validation_json",
            "output": "output_json",
            "error": "error_json",
            "fallback": "fallback_json",
        }
        sets, values = [], []
        for key, value in fields.items():
            column = columns.get(key, key)
            if column not in STORED_COLUMNS:  # column names are code, never input
                raise ValueError(f"unknown render column {column}")
            sets.append(f"{column}=?")
            values.append(json.dumps(value, sort_keys=True) if key in columns else value)
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            statement = f"UPDATE render_jobs SET {', '.join(sets)} WHERE id=?"  # noqa: S608
            conn.execute(statement, (*values, render_id))

    # -- the job ---------------------------------------------------------------------

    def _project(self, project_id: str) -> dict[str, Any]:
        try:
            return self.projects.get(project_id)
        except (NotFoundError, ProjectError) as exc:
            raise RenderError(
                "render.unknown_project", "That project does not exist.", status=404
            ) from exc

    @staticmethod
    def _check_sources(state: dict[str, Any]) -> None:
        used = {
            s["asset_id"] for t in state["document"]["project"]["tracks"] for s in t["segments"]
        }
        for source in state["sources"]:
            if source["asset_id"] in used and source["state"] != "available_unverified":
                raise RenderError(
                    "render.source_unavailable",
                    "A clip in this project is missing, changed or needs relinking. Relink it "
                    "before rendering.",
                    details={"asset_id": source["asset_id"], "state": source["state"]},
                )
        for binding in state["document"]["sources"]:
            if binding["asset_id"] in used and binding.get("requires_relink"):
                raise RenderError(
                    "render.source_unavailable", "A clip in this project needs relinking first."
                )

    def _verify(
        self, state: dict[str, Any], cancel: threading.Event
    ) -> tuple[dict[str, SourceFacts], dict[str, Path], dict[str, tuple[int, int]]]:
        """Full SHA-256 of each referenced original against the project identity."""
        bindings = {s["asset_id"]: s for s in state["document"]["sources"]}
        used: list[str] = []
        for track in state["document"]["project"]["tracks"]:
            for segment in track["segments"]:
                if segment["asset_id"] not in used:
                    used.append(segment["asset_id"])
        facts: dict[str, SourceFacts] = {}
        paths: dict[str, Path] = {}
        stats: dict[str, tuple[int, int]] = {}
        with contextlib.closing(self.database.connect()) as conn:
            for aid in used:
                repo = AssetRepository(conn)
                path = readable_source(self.library, repo.location(aid))
                if path is None:
                    raise RenderError(
                        "render.source_unavailable", "A clip's original file is missing."
                    )
                before = path.stat()
                if content_hash(path, cancel) != bindings[aid]["sha256"]:
                    raise RenderError(
                        "render.source_changed",
                        "A clip's original file changed since it was added. Relink it before "
                        "rendering.",
                        details={"asset_id": aid},
                    )
                asset = repo.get(aid)
                video = asset.video
                if video is None:
                    raise RenderError("render.source_unavailable", "A clip has no video stream.")
                rate = video.average_frame_rate or video.frame_rate
                transfer = proxy_geometry(video).hdr_transfer
                facts[aid] = SourceFacts(
                    aid,
                    bindings[aid]["sha256"],
                    bindings[aid]["original_name"],
                    bool(asset.audio),
                    (rate.num, rate.den) if rate and rate.num > 0 and rate.den > 0 else None,
                    ToneMapSettings(transfer) if transfer else None,  # type: ignore[arg-type]
                    *display_size(video),
                )
                paths[aid] = path
                stats[aid] = (before.st_size, before.st_mtime_ns)
        return facts, paths, stats

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
        project_id = params["project_id"]
        encoder_id = params.get("encoder", CPU.id)
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            conn.execute(
                "INSERT INTO render_jobs (id, story_id, preset_id, status, progress, created_at, "
                "encoder) VALUES (?, ?, ?, 'rendering', 0, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "status='rendering', progress=0, error_json=NULL, fallback_json=NULL, "
                "output_json=NULL, validation_json=NULL, finished_at=NULL",
                (job_id, project_id, params["preset_id"], utc_now(), encoder_id),
            )
        staging = self.root / STAGING / job_id
        try:
            report(0, 1000, "Checking clips")
            state = self._project(project_id)
            self._check_revision(state, params)
            privacy_summary = self._privacy(state)
            self._check_sources(state)
            self._store(job_id, project_revision=state["revision"])
            preset = self.presets.get(params["preset_id"])
            encoder = self._encoder(encoder_id)
            facts, paths, stats = self._verify(state, cancel)
            tool = self.tools.tool("ffmpeg")
            plan = build_plan(
                state["document"],
                facts,
                preset,
                encoder,
                ffmpeg_version=tool.version or "unknown",
                omit_text=bool(params.get("omit_text", False)),
                layout_profile=self._layout_profile(state["document"]),
                review_layout=bool(params.get("review_layout", False)),
            )
            plan["privacy_review"] = privacy_summary
            self._store(job_id, plan=plan)
            free = shutil.disk_usage(self.root).free
            if free < estimate_bytes(plan) + DISK_RESERVE:
                raise RenderError(
                    "render.disk_full",
                    "There is not enough free space in the library folder for this render.",
                )
            remove_tree(staging)
            staging.mkdir(parents=True)
            (staging / "graph.txt").write_text(plan["command"]["filter_complex"], "utf-8")
            for f in facts.values():
                if f.tone_map is not None:
                    text, _ = lut(f.tone_map)
                    (staging / LUT_NAMES[f.tone_map.transfer]).write_text(text, "ascii")
            output = staging / "render.mp4"
            ordered = [paths[s["asset_id"]] for s in plan["sources"]]
            argv = materialize(plan["command"]["argv"], ordered, output)
            total_us = plan["duration_ms"] * 1000
            buffer = bytearray()

            def on_stdout(block: bytes) -> None:
                buffer.extend(block)
                while b"\n" in buffer:
                    line, _, rest = bytes(buffer).partition(b"\n")
                    buffer[:] = rest
                    key, _, value = line.decode("ascii", "replace").strip().partition("=")
                    if key in ("out_time_us", "out_time_ms") and value.isdigit():
                        done = min(total_us, int(value))
                        report(50 + done * 850 // max(1, total_us), 1000, "Rendering")

            report(50, 1000, "Rendering")
            try:
                result = run_tool(
                    [*tool.command, *argv],
                    timeout_s=max(600.0, 20 * plan["duration_ms"] / 1000),
                    cancel=cancel,
                    on_stdout=on_stdout,
                    cwd=staging,
                    redactor=Redactor([str(staging), *(str(p.parent) for p in ordered)]),
                )
            except ToolCancelled:
                raise
            except ToolError as exc:
                raise failure_from_stderr(exc.stderr_tail, encoder) from exc
            if cancel.is_set():
                raise RenderCancelled
            if result.returncode:
                raise failure_from_stderr(result.stderr_tail, encoder)
            report(900, 1000, "Validating")
            validation = validate_output(self.tools, output, plan, ordered, cancel)
            self._store(job_id, validation=validation)
            if not validation["passed"]:
                failed = [c["name"] for c in validation["checks"] if not c["passed"]]
                raise RenderError(
                    "render.validation_failed",
                    "The rendered file failed validation and was not kept: " + ", ".join(failed),
                )
            for aid, before in stats.items():
                info = paths[aid].stat()
                if (info.st_size, info.st_mtime_ns) != before:
                    raise RenderError("render.source_changed", "A clip changed during rendering.")
            final = self._finish(job_id, project_id, plan, output, staging)
            report(1000, 1000, "Render ready")
            return final
        except (ToolCancelled, AnalysisCancelled, RenderCancelled) as exc:
            self._store(
                job_id,
                status="cancelled",
                finished_at=utc_now(),
                error={
                    "code": "render.cancelled",
                    "message": "The render was cancelled.",
                    "retryable": True,
                },
            )
            raise RenderCancelled from exc
        except RenderError as exc:
            fallback = None
            if exc.code == "render.hardware_encoder_failed":
                fallback = {"encoder": CPU.id, "reason": exc.message}
            self._store(
                job_id,
                status="failed",
                finished_at=utc_now(),
                error={"code": exc.code, "message": exc.message, "retryable": True},
                **({"fallback": fallback} if fallback else {}),
            )
            raise RenderFailed(exc, self.get(job_id)) from exc
        except OSError as exc:
            error = RenderError(
                "render.disk_full" if getattr(exc, "errno", None) == 28 else "render.io_failed",
                "The render could not be written to the library folder.",
            )
            self._store(
                job_id,
                status="failed",
                finished_at=utc_now(),
                error={"code": error.code, "message": error.message, "retryable": True},
            )
            raise RenderFailed(error, self.get(job_id)) from exc
        finally:
            remove_tree(staging)

    def _finish(
        self,
        job_id: str,
        project_id: str,
        plan: dict[str, Any],
        output: Path,
        staging: Path,
    ) -> dict[str, Any]:
        size = output.stat().st_size
        digest = content_hash(output, threading.Event())
        finished = utc_now()
        with contextlib.closing(self.database.connect()) as conn:
            row = conn.execute(
                "SELECT r.project_revision, s.session_id FROM render_jobs r "
                "LEFT JOIN stories s ON s.id = r.story_id WHERE r.id = ?",
                (job_id,),
            ).fetchone()
            detectors, profiles = detector_versions(conn, row["session_id"] if row else None)
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "created_at": finished,
            "app_version": __version__,
            "render_id": job_id,
            "project_id": project_id,
            "sources": [
                {"sha256": s["sha256"], "original_name": s["original_name"]}
                for s in plan["sources"]
            ],
            "segments": [
                {"source": s["source"], "in_ms": s["in_ms"], "out_ms": s["out_ms"]}
                for s in plan["segments"]
            ],
            "render": {
                "preset_id": plan["preset"]["id"],
                "width": plan["output"]["width"],
                "height": plan["output"]["height"],
                "fps": plan["output"]["fps"],
                "layout": "vertical-v1"
                if plan["output"]["height"] > plan["output"]["width"]
                else "fit",
            },
            "encoder": plan["encoder"]["id"],
            "tools": {
                "ffmpeg": plan["tools"]["ffmpeg"],
                "render_engine": plan["tools"]["render_engine"],
            },
            "output": {"sha256": digest, "size_bytes": size, "duration_ms": plan["duration_ms"]},
            "privacy_review": plan["privacy_review"],
            "detectors": detectors,
            "profiles": profiles,
        }
        if row is not None and row["project_revision"] is not None:
            manifest["project_revision"] = row["project_revision"]
        manifest = normalize(load("export-manifest", manifest))
        # The sidecar and the stored copy use the same canonical bytes (M27).
        (staging / "render.manifest.json").write_text(canonical_json(manifest), "utf-8")
        target = self.root / RENDERS / project_id
        target.mkdir(parents=True, exist_ok=True)
        video = target / f"{job_id}.mp4"
        sidecar = target / f"{job_id}.manifest.json"
        os.replace(staging / "render.manifest.json", sidecar)
        os.replace(output, video)
        record_output = {
            "relative_path": f"renders/{project_id}/{job_id}.mp4",
            "manifest_relative_path": f"renders/{project_id}/{job_id}.manifest.json",
            "size_bytes": size,
            "sha256": digest,
            "duration_ms": plan["duration_ms"],
        }
        self._store(
            job_id,
            status="ready",
            progress=1.0,
            finished_at=finished,
            output=record_output,
            manifest_json=json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            output_path=record_output["relative_path"],
            manifest_path=record_output["manifest_relative_path"],
        )
        return self.get(job_id)
