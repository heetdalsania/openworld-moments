# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built-in job handlers.

* ``diagnostic`` (M03): synthetic job used by integration tests and the UI to
  exercise progress, cancellation, failure, and crash recovery without media.
* ``probe`` (M04): read-only FFprobe of one explicitly selected file; the
  normalized ``MediaProbe`` becomes the job's ``result``.
* ``import``, ``relink``, ``check_sources`` (M05): the safe import pipeline
  (``openworld_moments.ingest``). They need the library database.
* ``fingerprint`` (M06): restartable fingerprint backfill.
* ``proxy`` (M08): one asset's derived playback media (proxy, filmstrip,
  waveform), ``openworld_moments.derived``.
* ``group`` (M11): rebuild unreviewed sessions from capture times and metadata,
  ``openworld_moments.sessions``.
* ``align`` (M12): find repeated footage between adjacent session clips,
  ``openworld_moments.alignment``.

* ``analyze`` (M14): isolated, cached built-in detector runs over derived media.
* ``transcribe`` (M18): optional local whisper.cpp transcription, per clip, cached.

Later product handlers (transcribe, ...) arrive in their milestones.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openworld_moments.alignment.service import AlignCancelled, Aligner
from openworld_moments.derived.service import DerivedCancelled, DerivedFailure, DerivedMedia
from openworld_moments.detectors.profiles import SLUG
from openworld_moments.detectors.sdk import AnalysisCancelled, AnalysisError
from openworld_moments.detectors.service import Analyzer
from openworld_moments.fingerprints.service import (
    FingerprintCancelled,
    Fingerprinter,
    FingerprintFailure,
)
from openworld_moments.ingest.files import ImportCancelled
from openworld_moments.ingest.importer import Importer, ImportFailure
from openworld_moments.jobs.engine import Cancelled, JobContext, JobFailure, JobHandler
from openworld_moments.media.probe import (
    DEFAULT_TIMEOUT_S,
    ProbeCancelled,
    ProbeError,
    check_path_param,
    probe_file,
)
from openworld_moments.media.tools import MediaTools
from openworld_moments.sessions.service import GroupCancelled, SessionError, SessionService
from openworld_moments.storage import Database, NotFoundError
from openworld_moments.stories.service import StoryCancelled, StoryError, StoryRequest, StoryService
from openworld_moments.transcripts.service import Transcriber
from openworld_moments.transcripts.whisper import TranscriptionCancelled, TranscriptionError

MAX_STEPS = 10_000
MAX_STEP_MS = 60_000
MAX_IMPORT_PATHS = 100
IMPORT_MODES = ("reference", "managed")
SOURCE_KINDS = ("xbox", "playstation", "obs", "capture_card", "phone_upload", "other")
_ASSET_ID = re.compile(r"^ast_[0-9A-HJKMNP-TV-Z]{26}$")


def _int_param(
    params: Mapping[str, Any], name: str, default: int | None, lo: int, hi: int
) -> int | None:
    value = params.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"'{name}' must be an integer between {lo} and {hi}")
    return value


def validate_diagnostic(params: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(params) - {"steps", "step_ms", "fail_at"}
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    steps = _int_param(params, "steps", 10, 1, MAX_STEPS) or 10
    clean: dict[str, Any] = {
        "steps": steps,
        "step_ms": _int_param(params, "step_ms", 100, 0, MAX_STEP_MS),
    }
    fail_at = _int_param(params, "fail_at", None, 1, steps)
    if fail_at is not None:
        clean["fail_at"] = fail_at
    return clean


def run_diagnostic(ctx: JobContext) -> None:
    steps: int = ctx.params["steps"]
    step_ms: int = ctx.params["step_ms"]
    fail_at: int | None = ctx.params.get("fail_at")
    ctx.progress(0, steps, "Starting")
    for step in range(1, steps + 1):
        ctx.sleep(step_ms / 1000)
        if fail_at == step:
            raise JobFailure(
                "diagnostic.requested_failure",
                f"Failed at step {step} as requested.",
                retryable=True,
            )
        ctx.progress(step, steps, f"Step {step} of {steps}")


DIAGNOSTIC = JobHandler(
    kind="diagnostic",
    run=run_diagnostic,
    validate=validate_diagnostic,
    first_state="analyzing",
    requeue_on_interrupt=True,
    max_attempts=3,
)

BUILTIN_HANDLERS = {DIAGNOSTIC.kind: DIAGNOSTIC}


def validate_probe(params: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(params) - {"path"}
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    return {"path": check_path_param(params.get("path"))}


def probe_handler(tools: MediaTools, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> JobHandler:
    """The ``probe`` job. Idempotent (read-only), so it is requeued after a crash."""

    def run(ctx: JobContext) -> dict[str, Any]:
        ctx.check_cancelled()
        try:
            return probe_file(
                Path(ctx.params["path"]),
                tools.tool("ffprobe"),
                timeout_s=timeout_s,
                cancel=ctx.cancel_event,
            )
        except ProbeCancelled as exc:
            raise Cancelled from exc
        except ProbeError as exc:
            raise JobFailure(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                details=exc.details,
                stderr_tail=exc.stderr_tail,
            ) from exc

    return JobHandler(
        kind="probe",
        run=run,
        validate=validate_probe,
        first_state="probing",
        requeue_on_interrupt=True,
        max_attempts=3,
    )


def _reject_unknown(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")


def validate_import(params: Mapping[str, Any]) -> dict[str, Any]:
    """ImportRequest (contract import.schema.json#/$defs/ImportRequest), normalized."""
    _reject_unknown(params, {"paths", "mode", "recursive", "source_kind"})
    paths = params.get("paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_IMPORT_PATHS:
        raise ValueError(f"'paths' must be a list of 1 to {MAX_IMPORT_PATHS} absolute paths")
    clean_paths = []
    for i, value in enumerate(paths):
        try:
            clean_paths.append(check_path_param(value))
        except ValueError as exc:
            raise ValueError(str(exc).replace("'path'", f"'paths[{i}]'", 1)) from exc
    mode = params.get("mode")
    if mode not in IMPORT_MODES:
        raise ValueError("'mode' must be 'reference' or 'managed'")
    recursive = params.get("recursive", False)
    if not isinstance(recursive, bool):
        raise ValueError("'recursive' must be true or false")
    source_kind = params.get("source_kind", "other")
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"'source_kind' must be one of {', '.join(SOURCE_KINDS)}")
    return {
        "paths": clean_paths,
        "mode": mode,
        "recursive": recursive,
        "source_kind": source_kind,
    }


def validate_relink(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, {"asset_id", "path"})
    asset_id = params.get("asset_id")
    if not isinstance(asset_id, str) or not _ASSET_ID.match(asset_id):
        raise ValueError("'asset_id' must be an asset ID")
    return {"asset_id": asset_id, "path": check_path_param(params.get("path"))}


MAX_FINGERPRINT_ASSETS = 10_000


def validate_fingerprint(params: Mapping[str, Any]) -> dict[str, Any]:
    """FingerprintRequest (contract fingerprint.schema.json#/$defs/FingerprintRequest)."""
    _reject_unknown(params, {"asset_ids", "force"})
    clean: dict[str, Any] = {}
    force = params.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("'force' must be true or false")
    clean["force"] = force
    if "asset_ids" in params:
        ids = params["asset_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_FINGERPRINT_ASSETS:
            raise ValueError(f"'asset_ids' must list 1 to {MAX_FINGERPRINT_ASSETS} asset IDs")
        if any(not isinstance(i, str) or not _ASSET_ID.match(i) for i in ids):
            raise ValueError("'asset_ids' must contain asset IDs only")
        if len(set(ids)) != len(ids):
            raise ValueError("'asset_ids' must not repeat an asset")
        clean["asset_ids"] = list(ids)
    return clean


def fingerprint_handler(fingerprinter: Fingerprinter) -> JobHandler:
    """The ``fingerprint`` backfill. Each asset commits on its own and only missing or
    stale fingerprints are computed, so a requeued job continues where it stopped."""

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            return fingerprinter.backfill(
                ctx.params, cancel=ctx.cancel_event, progress=ctx.progress
            )
        except FingerprintCancelled as exc:
            raise Cancelled from exc
        except FingerprintFailure as exc:
            raise JobFailure(exc.code, exc.message, retryable=exc.retryable) from exc

    return JobHandler("fingerprint", run, validate_fingerprint, "fingerprinting", True, 3)


DERIVED_KINDS = ("proxy", "filmstrip", "waveform")


def validate_derived(params: Mapping[str, Any]) -> dict[str, Any]:
    """DerivedMediaRequest (contract derived-media.schema.json#/$defs/DerivedMediaRequest)."""
    _reject_unknown(params, {"asset_id", "artifacts", "proxy_policy", "force"})
    asset_id = params.get("asset_id")
    if not isinstance(asset_id, str) or not _ASSET_ID.match(asset_id):
        raise ValueError("'asset_id' must be an asset ID")
    clean: dict[str, Any] = {"asset_id": asset_id}
    artifacts = params.get("artifacts", list(DERIVED_KINDS))
    if (
        not isinstance(artifacts, list)
        or not 1 <= len(artifacts) <= len(DERIVED_KINDS)
        or any(a not in DERIVED_KINDS for a in artifacts)
        or len(set(artifacts)) != len(artifacts)
    ):
        raise ValueError("'artifacts' must list distinct kinds: proxy, filmstrip, waveform")
    clean["artifacts"] = [k for k in DERIVED_KINDS if k in artifacts]
    policy = params.get("proxy_policy", "auto")
    if policy not in ("auto", "always"):
        raise ValueError("'proxy_policy' must be 'auto' or 'always'")
    clean["proxy_policy"] = policy
    force = params.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("'force' must be true or false")
    clean["force"] = force
    return clean


def derived_handler(derived: DerivedMedia) -> JobHandler:
    """The ``proxy`` job. Artifacts are committed one by one and current ones are cache
    hits, so a requeued job continues where it stopped."""

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            return derived.generate(
                ctx.params, job_id=ctx.job_id, cancel=ctx.cancel_event, progress=ctx.progress
            )
        except DerivedCancelled as exc:
            raise Cancelled from exc
        except DerivedFailure as exc:
            raise JobFailure(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                details=exc.details,
                stderr_tail=exc.stderr_tail,
            ) from exc

    return JobHandler("proxy", run, validate_derived, "proxying", True, 3)


MIN_GAP_MS, MAX_GAP_MS = 60_000, 86_400_000


def validate_group(params: Mapping[str, Any]) -> dict[str, Any]:
    """GroupRequest (contract session.schema.json#/$defs/GroupRequest)."""
    _reject_unknown(params, {"max_gap_ms"})
    clean: dict[str, Any] = {}
    gap = _int_param(params, "max_gap_ms", None, MIN_GAP_MS, MAX_GAP_MS)
    if gap is not None:
        clean["max_gap_ms"] = gap
    return clean


def group_handler(service: SessionService) -> JobHandler:
    """The ``group`` job. Recomputation is idempotent, so a requeue is safe."""

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            return service.recompute(ctx.params, cancel=ctx.cancel_event, progress=ctx.progress)
        except GroupCancelled as exc:
            raise Cancelled from exc

    return JobHandler("group", run, validate_group, "grouping", True, 3)


_SESSION_ID = re.compile(r"^ses_[0-9A-HJKMNP-TV-Z]{26}$")
MAX_ALIGN_SESSIONS = 10_000


def validate_align(params: Mapping[str, Any]) -> dict[str, Any]:
    """AlignRequest (contract overlap.schema.json#/$defs/AlignRequest)."""
    _reject_unknown(params, {"session_ids", "force"})
    force = params.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("'force' must be true or false")
    clean: dict[str, Any] = {"force": force}
    if "session_ids" in params:
        ids = params["session_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_ALIGN_SESSIONS:
            raise ValueError(f"'session_ids' must list 1 to {MAX_ALIGN_SESSIONS} session IDs")
        if any(not isinstance(i, str) or not _SESSION_ID.match(i) for i in ids):
            raise ValueError("'session_ids' must contain session IDs only")
        if len(set(ids)) != len(ids):
            raise ValueError("'session_ids' must not repeat a session")
        clean["session_ids"] = list(ids)
    return clean


def align_handler(aligner: Aligner) -> JobHandler:
    """The ``align`` job. Pair results are committed one by one and current ones are
    cache hits, so a requeued job continues where it stopped."""

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            return aligner.run(ctx.params, cancel=ctx.cancel_event, progress=ctx.progress)
        except AlignCancelled as exc:
            raise Cancelled from exc
        except FingerprintFailure as exc:
            raise JobFailure(exc.code, exc.message, retryable=exc.retryable) from exc
        except SessionError as exc:
            raise JobFailure(exc.code, exc.message) from exc

    return JobHandler("align", run, validate_align, "analyzing", True, 3)


def validate_check_sources(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, set())
    return {}


def analyze_handler(analyzer: Analyzer) -> JobHandler:
    def validate(params: Mapping[str, Any]) -> dict[str, Any]:
        _reject_unknown(params, {"session_id", "profile_id", "locale", "force"})
        sid = params.get("session_id")
        pid = params.get("profile_id")
        if not isinstance(sid, str) or not _SESSION_ID.fullmatch(sid):
            raise ValueError("session_id: expected a session ID")
        if not isinstance(pid, str) or not SLUG.fullmatch(pid):
            raise ValueError("profile_id: expected a profile slug")
        if not isinstance(params.get("force", False), bool):
            raise ValueError("force: expected a boolean")
        locale = params.get("locale")
        if locale is not None and (
            not isinstance(locale, str)
            or not re.fullmatch(r"[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?", locale)
        ):
            raise ValueError("locale: expected a language tag")
        try:
            analyzer.profile(pid)
        except AnalysisError as exc:
            raise ValueError(exc.message) from exc
        return dict(params)

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            result = analyzer.run(
                ctx.params, job_id=ctx.job_id, cancel=ctx.cancel_event, progress=ctx.progress
            )
        except AnalysisCancelled as exc:
            raise Cancelled from exc
        except AnalysisError as exc:
            raise JobFailure(exc.code, exc.message) from exc
        # A partial failure keeps successful detector events and the detailed result,
        # but must not make the durable job look wholly successful.
        if any(o["status"] == "failed" for o in result["outcomes"]):
            raise JobFailure(
                "analysis.partial_failure",
                "Some detectors failed; successful results are kept.",
                retryable=True,
                result=result,
            )
        return result

    return JobHandler("analyze", run, validate, "analyzing", True, 3)


_MODEL_NAME = re.compile(r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$")


def transcribe_handler(transcriber: Transcriber) -> JobHandler:
    def validate(params: Mapping[str, Any]) -> dict[str, Any]:
        _reject_unknown(params, {"session_id", "model", "language", "force"})
        sid, model = params.get("session_id"), params.get("model")
        if not isinstance(sid, str) or not _SESSION_ID.fullmatch(sid):
            raise ValueError("session_id: expected a session ID")
        if not isinstance(model, str) or len(model) > 64 or not _MODEL_NAME.fullmatch(model):
            raise ValueError("model: expected an installed speech-model name")
        language = params.get("language", "auto")
        if not isinstance(language, str) or not re.fullmatch(r"auto|[a-z]{2,3}", language):
            raise ValueError("language: expected 'auto' or a language code")
        if not isinstance(params.get("force", False), bool):
            raise ValueError("force: expected a boolean")
        try:
            # Transcription is optional: refuse clearly instead of downloading anything.
            transcriber.check_request(model)
        except TranscriptionError as exc:
            raise ValueError(exc.message) from exc
        return {**params, "language": language}

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            result = transcriber.run(
                ctx.params, job_id=ctx.job_id, cancel=ctx.cancel_event, progress=ctx.progress
            )
        except TranscriptionCancelled as exc:
            raise Cancelled from exc
        except TranscriptionError as exc:
            raise JobFailure(exc.code, exc.message) from exc
        if any(o["status"] == "failed" for o in result["outcomes"]):
            raise JobFailure(
                "transcription.partial_failure",
                "Some clips could not be transcribed; completed clips are kept.",
                retryable=True,
                result=result,
            )
        return result

    return JobHandler("transcribe", run, validate, "transcribing", True, 3)


def story_handler(service: StoryService) -> JobHandler:
    def validate(params: Mapping[str, Any]) -> dict[str, Any]:
        sid = params.get("session_id")
        if not isinstance(sid, str) or not _SESSION_ID.fullmatch(sid):
            raise ValueError("session_id: expected a session ID")
        try:
            request = StoryRequest.model_validate(
                {k: v for k, v in params.items() if k != "session_id"}
            )
        except ValueError as exc:
            raise ValueError("Choose valid story preset and boundary settings.") from exc
        return {"session_id": sid, **request.model_dump(exclude_none=True)}

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            return service.generate(
                ctx.params["session_id"],
                StoryRequest.model_validate(
                    {k: v for k, v in ctx.params.items() if k != "session_id"}
                ),
                cancel=ctx.cancel_event,
                progress=ctx.progress,
            )
        except StoryCancelled as exc:
            raise Cancelled from exc
        except StoryError as exc:
            raise JobFailure(exc.code, exc.message, retryable=exc.status == 409) from exc
        except NotFoundError as exc:
            raise JobFailure("story.session_missing", "That session no longer exists.") from exc

    return JobHandler("story", run, validate, "analyzing", True, 3)


def _job_failure(exc: ImportFailure) -> JobFailure:
    return JobFailure(
        exc.code,
        exc.message,
        retryable=exc.retryable,
        details=exc.details,
        stderr_tail=exc.stderr_tail,
        result=exc.result,
    )


def import_handlers(importer: Importer) -> dict[str, JobHandler]:
    """``import``, ``relink``, and ``check_sources``. All are idempotent (identical bytes
    resolve to one asset; relink and the check only converge state), so a worker crash
    requeues them."""

    def run_import(ctx: JobContext) -> dict[str, Any]:
        try:
            return importer.run_import(
                ctx.params,
                job_id=ctx.job_id,
                cancel=ctx.cancel_event,
                progress=ctx.progress,
                set_state=ctx.set_state,
            )
        except ImportCancelled as exc:
            raise Cancelled from exc
        except ImportFailure as exc:
            raise _job_failure(exc) from exc

    def run_relink(ctx: JobContext) -> dict[str, Any]:
        try:
            return importer.relink(ctx.params, job_id=ctx.job_id, cancel=ctx.cancel_event)
        except ImportCancelled as exc:
            raise Cancelled from exc
        except ImportFailure as exc:
            raise _job_failure(exc) from exc

    def run_check(ctx: JobContext) -> dict[str, Any]:
        try:
            return importer.check_sources(cancel=ctx.cancel_event, progress=ctx.progress)
        except ImportCancelled as exc:
            raise Cancelled from exc

    handlers = [
        JobHandler("import", run_import, validate_import, "probing", True, 3),
        JobHandler("relink", run_relink, validate_relink, "fingerprinting", True, 3),
        JobHandler("check_sources", run_check, validate_check_sources, "analyzing", True, 3),
    ]
    return {h.kind: h for h in handlers}


def build_handlers(
    tools: MediaTools,
    *,
    probe_timeout_s: float = DEFAULT_TIMEOUT_S,
    database: Database | None = None,
    derived: DerivedMedia | None = None,
    transcriber: Transcriber | None = None,
) -> dict[str, JobHandler]:
    """Every handler the worker serves. Import handlers need the library ``database``.
    Pass the API's ``derived`` service so jobs and cleanup share one lock."""
    probe = probe_handler(tools, timeout_s=probe_timeout_s)
    handlers = {**BUILTIN_HANDLERS, probe.kind: probe}
    if database is not None:
        importer = Importer(database, tools, probe_timeout_s=probe_timeout_s)
        handlers.update(import_handlers(importer))
        fingerprint = fingerprint_handler(importer.fingerprinter)
        handlers[fingerprint.kind] = fingerprint
        media = derived or DerivedMedia(database, tools)
        proxy = derived_handler(media)
        handlers[proxy.kind] = proxy
        grouper = group_handler(SessionService(database))
        handlers[grouper.kind] = grouper
        aligner = align_handler(Aligner(database, importer.fingerprinter))
        handlers[aligner.kind] = aligner
        analysis = analyze_handler(Analyzer(database, tools, media))
        handlers[analysis.kind] = analysis
        speech = transcribe_handler(transcriber or Transcriber(database, tools, media))
        handlers[speech.kind] = speech
        story = story_handler(StoryService(database))
        handlers[story.kind] = story
    return handlers
