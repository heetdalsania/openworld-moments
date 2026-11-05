# SPDX-License-Identifier: AGPL-3.0-or-later
"""Built-in job handlers.

M03 ships only the synthetic ``diagnostic`` job, used by integration tests and
the UI to exercise progress, cancellation, failure, and crash recovery without
touching media. Product handlers (import, analyze, ...) arrive in later milestones.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openworld_moments.jobs.engine import JobContext, JobFailure, JobHandler

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
