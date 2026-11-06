# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built-in job handlers.

* ``diagnostic`` (M03): synthetic job used by integration tests and the UI to
  exercise progress, cancellation, failure, and crash recovery without media.
* ``probe`` (M04): read-only FFprobe of one explicitly selected file; the
  normalized ``MediaProbe`` becomes the job's ``result``.
* ``import``, ``relink``, ``check_sources`` (M05): the safe import pipeline
  (``openworld_moments.ingest``). They need the library database.

Later product handlers (analyze, proxy, ...) arrive in their milestones.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
from openworld_moments.storage import Database

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


def validate_check_sources(params: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(params, set())
    return {}


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
                ctx.params, job_id=ctx.job_id, cancel=ctx.cancel_event, progress=ctx.progress
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
) -> dict[str, JobHandler]:
    """Every handler the worker serves. Import handlers need the library ``database``."""
    probe = probe_handler(tools, timeout_s=probe_timeout_s)
    handlers = {**BUILTIN_HANDLERS, probe.kind: probe}
    if database is not None:
        importer = Importer(database, tools, probe_timeout_s=probe_timeout_s)
        handlers.update(import_handlers(importer))
    return handlers
