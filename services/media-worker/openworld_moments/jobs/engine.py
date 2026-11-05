# SPDX-License-Identifier: AGPL-3.0-or-later
"""Durable, cancellable job engine.

Every state change is written to SQLite (``jobs`` table) before it is
published, so a crash never loses a job record. Handlers are plain functions
that run in worker threads and talk back through a :class:`JobContext`.

States (contract ``Job``): ``queued`` → one or more active stages (``probing``,
``analyzing``, ...) → ``ready`` | ``cancelled`` | ``failed``. ``failed`` jobs
whose error is retryable can be queued again.

All engine methods run on the asyncio event loop thread, which owns the
database connection. Handler threads only touch the loop through
``call_soon_threadsafe``, which preserves the order of their updates.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.generated.job_event_schema import JobEvent
from openworld_moments_contracts.generated.job_schema import Job

from openworld_moments.ids import new_id
from openworld_moments.storage import Database, JobRepository, NotFoundError, transaction, utc_now
from openworld_moments.storage.repositories import SCHEMA_VERSION

log = logging.getLogger(__name__)

TERMINAL = frozenset({"ready", "cancelled", "failed"})
ACTIVE = frozenset(
    {
        "probing",
        "fingerprinting",
        "proxying",
        "grouping",
        "analyzing",
        "transcribing",
        "indexing",
        "rendering",
    }
)
SUBSCRIBER_QUEUE = 1000


def _not_before(*timestamps: str | None) -> str:
    """Now, but never earlier than the given contract timestamps.

    Guards against a system clock that moved backwards: a job's started_at and
    finished_at must not precede its earlier timestamps, or the contract (and the
    save) would reject the update and leave the job stuck.
    """
    now = utc_now()
    latest = max((t for t in timestamps if t), default=now, key=_instant)
    return now if _instant(now) >= _instant(latest) else latest


def _instant(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class Cancelled(Exception):
    """Raised inside a handler when cancellation was requested."""


class JobFailure(Exception):
    """Raised by a handler to fail its job with a contract error."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class EngineError(Exception):
    """A request the engine refuses. ``code`` maps to an API error code."""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class JobHandler:
    """How to run one job kind.

    ``validate`` checks params at submit time and returns the normalized params.
    ``requeue_on_interrupt`` marks the handler idempotent: if the worker stops
    mid-run, the job is queued again (up to ``max_attempts``) instead of failing.
    """

    kind: str
    run: Callable[[JobContext], None]
    validate: Callable[[Mapping[str, Any]], dict[str, Any]] = lambda params: dict(params)
    first_state: str = "analyzing"
    requeue_on_interrupt: bool = False
    max_attempts: int = 3


@dataclass
class _Running:
    cancel: threading.Event = field(default_factory=threading.Event)
    shutdown: bool = False


class JobContext:
    """Handed to a handler. Thread-safe; every method may be called from the handler thread."""

    def __init__(self, engine: JobEngine, job: Job, running: _Running) -> None:
        self._engine = engine
        self._running = running
        self.job_id = job.id
        self.params: dict[str, Any] = dict(job.params or {})
        self.attempt = job.attempt or 1
        self.correlation_id = job.correlation_id

    @property
    def cancelled(self) -> bool:
        return self._running.cancel.is_set()

    def check_cancelled(self) -> None:
        if self._running.cancel.is_set():
            raise Cancelled

    def sleep(self, seconds: float) -> None:
        """Wait, waking early (and raising Cancelled) if the job is cancelled."""
        if self._running.cancel.wait(timeout=max(0.0, seconds)):
            raise Cancelled

    def progress(self, done: int, total: int, message: str | None = None) -> None:
        if total < 1 or not 0 <= done <= total:
            raise ValueError(f"invalid progress {done}/{total}")
        self._engine._threadsafe(self._engine._update_progress, self.job_id, done, total, message)

    def set_state(self, state: str) -> None:
        if state not in ACTIVE:
            raise ValueError(f"{state!r} is not an active job state")
        self._engine._threadsafe(self._engine._update_state, self.job_id, state)


class Subscription:
    """An ordered stream of job events for one client."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[JobEvent | None] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE)
        self.overflowed = False


class JobEngine:
    def __init__(
        self,
        database: Database,
        handlers: Mapping[str, JobHandler],
        *,
        concurrency: int = 1,
    ) -> None:
        self.database = database
        self.handlers = dict(handlers)
        self.concurrency = concurrency
        self._conn: sqlite3.Connection | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._runners: list[asyncio.Task[None]] = []
        self._running: dict[str, _Running] = {}
        self._subscribers: set[Subscription] = set()
        self._seq = 0
        self._stopping = False

    # -- lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._conn = self.database.connect()
        self._recover_interrupted()
        for job in sorted(self._repo.list_unfinished(), key=lambda j: (j.created_at, j.id)):
            if job.state == "queued":
                self._queue.put_nowait(job.id)
        self._runners = [asyncio.create_task(self._runner()) for _ in range(self.concurrency)]

    async def stop(self, timeout: float = 10.0) -> None:
        """Stop accepting work and interrupt running handlers.

        Interrupted jobs keep their active state on disk; the next start applies
        the recovery rules, exactly as after a crash.
        """
        self._stopping = True
        for running in self._running.values():
            running.shutdown = True
            running.cancel.set()
        for task in self._runners:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.gather(*self._runners, return_exceptions=True), timeout)
        for sub in list(self._subscribers):
            self._close(sub)
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _repo(self) -> JobRepository:
        if self._conn is None:
            raise RuntimeError("engine is not started")
        return JobRepository(self._conn)

    # -- public operations ------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        try:
            return self._repo.get(job_id)
        except NotFoundError as exc:
            raise EngineError("job.not_found", f"job {job_id} not found", status=404) from exc

    def list(self, *, limit: int = 200) -> list[Job]:
        return self._repo.all(limit=limit)

    async def submit(
        self, kind: str, params: Mapping[str, Any] | None, correlation_id: str | None
    ) -> Job:
        if self._stopping:
            raise EngineError("worker.stopping", "the worker is shutting down", status=503)
        handler = self.handlers.get(kind)
        if handler is None:
            raise EngineError("job.unknown_kind", f"no handler for job kind {kind!r}", status=422)
        try:
            clean = handler.validate(params or {})
        except (ValueError, TypeError) as exc:
            raise EngineError("job.invalid_params", str(exc), status=422) from exc
        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": new_id("job"),
            "kind": kind,
            "state": "queued",
            "params": clean,
            "attempt": 1,
            "created_at": utc_now(),
        }
        if correlation_id:
            doc["correlation_id"] = correlation_id
        job = self._save(doc, "state")
        self._queue.put_nowait(job.id)
        return job

    async def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state == "cancelled":
            return job
        if job.state in TERMINAL:
            raise EngineError("job.not_cancellable", f"job is already {job.state}")
        running = self._running.get(job_id)
        if running is not None:
            running.cancel.set()  # the runner records 'cancelled' when the handler stops
            return job
        return self._finish(job, "cancelled")

    async def retry(self, job_id: str) -> Job:
        job = self.get(job_id)
        handler = self.handlers.get(job.kind)
        if job.state != "failed" or job.error is None or not job.error.retryable or handler is None:
            raise EngineError(
                "job.not_retryable", "only failed jobs with a retryable error can be retried"
            )
        attempt = (job.attempt or 1) + 1
        if attempt > handler.max_attempts:
            raise EngineError("job.max_attempts", f"job already ran {job.attempt} times")
        job = self._requeue(job, attempt, "Retry requested")
        self._queue.put_nowait(job.id)
        return job

    def subscribe(self) -> Subscription:
        sub = Subscription()
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscribers.discard(sub)

    # -- recovery ---------------------------------------------------------------------

    def _recover_interrupted(self) -> None:
        """Apply retry rules to jobs that were active when the worker last stopped."""
        for job in self._repo.list_unfinished():
            if job.state not in ACTIVE:
                continue
            handler = self.handlers.get(job.kind)
            attempt = (job.attempt or 1) + 1
            if handler and handler.requeue_on_interrupt and attempt <= handler.max_attempts:
                self._requeue(job, attempt, "Requeued after the worker stopped unexpectedly")
                log.info(
                    "job requeued after interruption", extra={"job_id": job.id, "attempt": attempt}
                )
            else:
                self._finish(
                    job,
                    "failed",
                    error={
                        "code": "job.interrupted",
                        "message": "The worker stopped while this job was running.",
                        "retryable": True,
                    },
                )
                log.info("interrupted job marked failed", extra={"job_id": job.id})

    # -- running ----------------------------------------------------------------------

    async def _runner(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_one(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one job kill the runner
                log.exception("job runner error", extra={"job_id": job_id})

    async def _run_one(self, job_id: str) -> None:
        job = self._repo.get(job_id)
        handler = self.handlers.get(job.kind)
        if job.state != "queued":
            return  # cancelled while queued
        if handler is None:
            self._finish(
                job,
                "failed",
                error={
                    "code": "job.unknown_kind",
                    "message": f"no handler for {job.kind}",
                    "retryable": False,
                },
            )
            return
        running = _Running()
        self._running[job_id] = running
        job = self._save(
            {
                **self._doc(job),
                "state": handler.first_state,
                "started_at": _not_before(job.created_at),
            },
            "state",
        )
        context = JobContext(self, job, running)
        try:
            await asyncio.to_thread(handler.run, context)
        except Cancelled:
            pass
        except JobFailure as exc:
            if not running.shutdown:
                self._finish(
                    self._repo.get(job_id),
                    "failed",
                    error={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                )
            return
        except Exception:
            log.exception("job handler crashed", extra={"job_id": job_id, "kind": job.kind})
            if not running.shutdown:
                self._finish(
                    self._repo.get(job_id),
                    "failed",
                    error={
                        "code": "job.handler_crashed",
                        "message": "The job stopped because of an internal error.",
                        "retryable": False,
                    },
                )
            return
        finally:
            self._running.pop(job_id, None)
            # Let progress callbacks queued by the handler thread land first.
            await asyncio.sleep(0)
        if running.shutdown:
            return  # leave the active state on disk; the next start recovers it
        current = self._repo.get(job_id)
        self._finish(current, "cancelled" if running.cancel.is_set() else "ready")

    # -- state changes (event loop thread only) ------------------------------------------

    def _threadsafe(self, fn: Callable[..., None], *args: Any) -> None:
        if self._loop is None:
            raise RuntimeError("engine is not started")
        self._loop.call_soon_threadsafe(fn, *args)

    def _update_progress(self, job_id: str, done: int, total: int, message: str | None) -> None:
        if job_id not in self._running or self._conn is None:
            return  # progress after the job finished: ignore
        doc = self._doc(self._repo.get(job_id))
        doc["progress"] = {"done": done, "total": total}
        if message is not None:
            doc["message"] = message
        self._save(doc, "progress")

    def _update_state(self, job_id: str, state: str) -> None:
        if job_id not in self._running or self._conn is None:
            return
        doc = self._doc(self._repo.get(job_id))
        if doc["state"] != state:
            doc["state"] = state
            doc.pop("progress", None)
            self._save(doc, "state")

    def _requeue(self, job: Job, attempt: int, message: str) -> Job:
        doc = self._doc(job)
        for key in ("progress", "error", "started_at", "finished_at"):
            doc.pop(key, None)
        doc.update(state="queued", attempt=attempt, message=message)
        return self._save(doc, "state")

    def _finish(self, job: Job, state: str, *, error: dict[str, Any] | None = None) -> Job:
        doc = self._doc(job)
        doc["state"] = state
        doc["finished_at"] = _not_before(job.created_at, job.started_at)
        if error is not None:
            if job.correlation_id:
                error = {**error, "correlation_id": job.correlation_id}
            doc["error"] = error
        return self._save(doc, "state")

    @staticmethod
    def _doc(job: Job) -> dict[str, Any]:
        doc = normalize(job)
        doc["schema_version"] = SCHEMA_VERSION
        return doc

    def _save(self, doc: dict[str, Any], kind: str) -> Job:
        job: Job = load("job", doc)  # type: ignore[assignment]
        conn = self._conn
        if conn is None:
            raise RuntimeError("engine is not started")
        with transaction(conn):
            JobRepository(conn).save(job)
        self._publish(job, kind)
        return job

    # -- events -----------------------------------------------------------------------

    def _publish(self, job: Job, kind: str) -> None:
        self._seq += 1
        event: JobEvent = load(  # type: ignore[assignment]
            "job-event",
            {
                "schema_version": SCHEMA_VERSION,
                "seq": self._seq,
                "emitted_at": utc_now(),
                "kind": kind,
                "job": self._doc(job),
            },
        )
        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.overflowed = True
                self._close(sub)

    def _close(self, sub: Subscription) -> None:
        """Detach a subscriber and wake it with the end-of-stream sentinel (None)."""
        self._subscribers.discard(sub)
        if sub.queue.full():  # make room for the sentinel
            with contextlib.suppress(asyncio.QueueEmpty):
                sub.queue.get_nowait()
        sub.queue.put_nowait(None)
