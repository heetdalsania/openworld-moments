# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crash-recovery and retry rules, driven directly against the engine."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.jobs.engine import JobEngine, JobHandler
from openworld_moments.jobs.handlers import BUILTIN_HANDLERS, DIAGNOSTIC
from openworld_moments.storage import Database, JobRepository, transaction

NOW = "2026-01-01T00:00:00Z"


def _seed(database: Database, job_id: str, kind: str, state: str, attempt: int = 1) -> None:
    doc: dict[str, Any] = {
        "schema_version": "1.1",
        "id": job_id,
        "kind": kind,
        "state": state,
        "params": {"steps": 1, "step_ms": 0},
        "attempt": attempt,
        "created_at": NOW,
        "started_at": NOW,
    }
    with closing(database.connect()) as conn, transaction(conn):
        JobRepository(conn).save(load("job", doc))  # type: ignore[arg-type]


def _get(database: Database, job_id: str) -> Any:
    with closing(database.connect()) as conn:
        return JobRepository(conn).get(job_id)


async def _start_then_stop(
    database: Database, handlers: dict[str, JobHandler], settle: float = 0.3
) -> None:
    engine = JobEngine(database, handlers)
    await engine.start()
    await asyncio.sleep(settle)
    await engine.stop()


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "database.sqlite3")


def test_interrupted_idempotent_job_is_requeued_and_completes(database: Database) -> None:
    job_id = "job_01JCBQ00000000000000000020"
    _seed(database, job_id, "diagnostic", "analyzing")
    asyncio.run(_start_then_stop(database, BUILTIN_HANDLERS))
    job = _get(database, job_id)
    assert job.state == "ready" and job.attempt == 2


def test_interrupted_job_at_max_attempts_fails_retryably(database: Database) -> None:
    job_id = "job_01JCBQ00000000000000000021"
    _seed(database, job_id, "diagnostic", "analyzing", attempt=DIAGNOSTIC.max_attempts)
    asyncio.run(_start_then_stop(database, BUILTIN_HANDLERS))
    job = _get(database, job_id)
    assert job.state == "failed" and job.error.code == "job.interrupted" and job.error.retryable


def test_interrupted_non_idempotent_job_fails(database: Database) -> None:
    job_id = "job_01JCBQ00000000000000000022"
    _seed(database, job_id, "analyze", "analyzing")
    handlers = {"analyze": JobHandler(kind="analyze", run=lambda ctx: None)}
    asyncio.run(_start_then_stop(database, handlers))
    assert _get(database, job_id).error.code == "job.interrupted"


def test_queued_jobs_survive_restart_and_run(database: Database) -> None:
    job_id = "job_01JCBQ00000000000000000023"
    _seed(database, job_id, "diagnostic", "queued")
    asyncio.run(_start_then_stop(database, BUILTIN_HANDLERS))
    assert _get(database, job_id).state == "ready"


def test_handler_crash_fails_the_job_without_leaking_details(database: Database) -> None:
    def boom(ctx: Any) -> None:
        raise RuntimeError("secret detail /Users/someone/file.mp4")

    async def scenario() -> str:
        engine = JobEngine(database, {"analyze": JobHandler(kind="analyze", run=boom)})
        await engine.start()
        job = await engine.submit("analyze", {}, None)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if engine.get(job.id).state == "failed":
                break
        await engine.stop()
        return job.id

    job = _get(database, asyncio.run(scenario()))
    assert job.error.code == "job.handler_crashed"
    assert "secret" not in job.error.message and "/Users" not in job.error.message


def test_graceful_stop_leaves_running_job_for_recovery(database: Database) -> None:
    async def scenario() -> str:
        engine = JobEngine(database, BUILTIN_HANDLERS)
        await engine.start()
        job = await engine.submit("diagnostic", {"steps": 1000, "step_ms": 10}, None)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if engine.get(job.id).state == "analyzing":
                break
        await engine.stop()
        return job.id

    job_id = asyncio.run(scenario())
    assert _get(database, job_id).state == "analyzing"  # not 'cancelled': it was interrupted


def test_clock_moving_backwards_does_not_strand_jobs(database: Database) -> None:
    """A job created 'in the future' (clock moved back) still runs to completion."""
    job_id = "job_01JCBQ00000000000000000024"
    doc = {
        "schema_version": "1.1",
        "id": job_id,
        "kind": "diagnostic",
        "state": "queued",
        "params": {"steps": 1, "step_ms": 0},
        "attempt": 1,
        "created_at": "2099-01-01T00:00:00Z",
    }
    with closing(database.connect()) as conn, transaction(conn):
        JobRepository(conn).save(load("job", doc))  # type: ignore[arg-type]
    asyncio.run(_start_then_stop(database, BUILTIN_HANDLERS))
    job = _get(database, job_id)
    assert job.state == "ready"
    assert job.started_at == job.finished_at == "2099-01-01T00:00:00Z"
