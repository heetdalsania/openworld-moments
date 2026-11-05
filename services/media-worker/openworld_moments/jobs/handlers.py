# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built-in job handlers.

* ``diagnostic`` (M03): synthetic job used by integration tests and the UI to
  exercise progress, cancellation, failure, and crash recovery without media.
* ``probe`` (M04): read-only FFprobe of one explicitly selected file; the
  normalized ``MediaProbe`` becomes the job's ``result``.

Product handlers (import, analyze, ...) arrive in later milestones.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openworld_moments.jobs.engine import Cancelled, JobContext, JobFailure, JobHandler
from openworld_moments.media.probe import (
    DEFAULT_TIMEOUT_S,
    ProbeCancelled,
    ProbeError,
    check_path_param,
    probe_file,
)
from openworld_moments.media.tools import MediaTools

MAX_STEPS = 10_000
MAX_STEP_MS = 60_000


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


def build_handlers(
    tools: MediaTools, *, probe_timeout_s: float = DEFAULT_TIMEOUT_S
) -> dict[str, JobHandler]:
    """Every handler the worker serves."""
    probe = probe_handler(tools, timeout_s=probe_timeout_s)
    return {**BUILTIN_HANDLERS, probe.kind: probe}
