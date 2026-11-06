# SPDX-License-Identifier: AGPL-3.0-or-later
"""Worker HTTP + WebSocket API (spec 9.4), bound to loopback and token-protected.

Every request, HTTP or WebSocket, passes :class:`Guard` first:

1. the peer must be a loopback address,
2. the Host header must name the bound loopback address (blocks DNS rebinding),
3. ``Authorization: Bearer <token>`` must match the per-launch token
   (constant-time comparison).

Responses carry ``X-Correlation-Id``; errors use the contract ``ErrorInfo`` shape.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openworld_moments_contracts import normalize
from openworld_moments_contracts.versioning import SUPPORTED_VERSION
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from openworld_moments import __version__
from openworld_moments.ids import new_id
from openworld_moments.jobs.engine import EngineError, JobEngine
from openworld_moments.storage import AssetRepository, NotFoundError

API_VERSION = 1
_CORRELATION = re.compile(r"^cor_[0-9A-HJKMNP-TV-Z]{26}$")
LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1"})
log = logging.getLogger(__name__)


@dataclass
class ApiSettings:
    token: str
    allowed_hosts: frozenset[str]
    require_loopback_peer: bool = True
    on_shutdown_request: Callable[[], None] = field(default=lambda: None)


def error_body(
    code: str, message: str, *, retryable: bool = False, correlation_id: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if correlation_id:
        body["correlation_id"] = correlation_id
    return body


class Guard:
    """Pure ASGI middleware so the same checks cover HTTP and WebSocket."""

    def __init__(self, app: ASGIApp, settings: ApiSettings) -> None:
        self.app = app
        self.settings = settings
        self._token = settings.token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        supplied = headers.get("x-correlation-id", "")
        correlation_id = supplied if _CORRELATION.match(supplied) else new_id("cor")
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        problem = self._check(scope, headers)
        if problem is not None:
            status, code, message = problem
            log.warning("request rejected", extra={"code": code, "correlation_id": correlation_id})
            await self._reject(
                scope,
                receive,
                send,
                status,
                error_body(code, message, correlation_id=correlation_id),
                correlation_id,
            )
            return

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (b"x-correlation-id", correlation_id.encode()),
                ]
            await send(message)

        await self.app(scope, receive, send_with_id)

    def _check(self, scope: Scope, headers: dict[str, str]) -> tuple[int, str, str] | None:
        peer = (scope.get("client") or ("", 0))[0]
        if self.settings.require_loopback_peer and peer not in LOOPBACK_PEERS:
            return 403, "auth.non_loopback_peer", "Requests must come from this computer."
        if headers.get("host", "") not in self.settings.allowed_hosts:
            return 403, "auth.bad_host", "Unexpected Host header."
        auth = headers.get("authorization", "")
        if not auth:
            return 401, "auth.missing_token", "Missing bearer token."
        scheme, _, value = auth.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            value.strip().encode(), self._token
        ):
            return 401, "auth.invalid_token", "Invalid bearer token."
        return None

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        body: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            if "websocket.http.response" not in scope.get("extensions", {}):
                await send({"type": "websocket.close", "code": 1008, "reason": body["code"]})
                return
            # Refuse the handshake with an HTTP response (WebSocket Denial Response).
            await send(
                {
                    "type": "websocket.http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"x-correlation-id", correlation_id.encode()),
                    ],
                }
            )
            await send({"type": "websocket.http.response.body", "body": json.dumps(body).encode()})
            return
        await JSONResponse(body, status_code=status, headers={"x-correlation-id": correlation_id})(
            scope, receive, send
        )


IDEMPOTENCY_KEY = r"^[A-Za-z0-9._:-]{1,128}$"


class SubmitJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class SubmitImport(BaseModel):
    """ImportRequest plus an optional idempotency key. Params are checked by the handler."""

    model_config = ConfigDict(extra="forbid")
    paths: list[Any]
    mode: Literal["reference", "managed"]
    recursive: bool = False
    source_kind: str = "other"
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class SubmitRelink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


def create_app(
    engine: JobEngine,
    settings: ApiSettings,
    *,
    on_ready: Callable[[], None] | None = None,
    capabilities: Callable[..., dict[str, Any]] | None = None,
) -> ASGIApp:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await engine.start()
        if on_ready is not None:
            on_ready()
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def cid(request: Request | WebSocket) -> str:
        return str(request.scope["state"]["correlation_id"])

    @app.exception_handler(EngineError)
    async def engine_error(request: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, correlation_id=cid(request)), status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
        return JSONResponse(
            error_body(
                "request.invalid", f"Invalid request: {fields}", correlation_id=cid(request)
            ),
            status_code=422,
        )

    @app.exception_handler(404)
    async def not_found(request: Request, _: Exception) -> JSONResponse:
        return JSONResponse(
            error_body("request.not_found", "No such endpoint.", correlation_id=cid(request)),
            status_code=404,
        )

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "schema_version": str(SUPPORTED_VERSION),
            "worker_version": __version__,
            "pid": os.getpid(),
        }

    @app.get("/v1/capabilities")
    async def get_capabilities(refresh: bool = False) -> dict[str, Any]:
        """Media tool report (same as ``doctor --json``). Runs the tools, so it is threaded."""
        if capabilities is None:
            raise EngineError("request.not_found", "No capability report.", status=404)
        return await asyncio.to_thread(capabilities, refresh=refresh)

    @app.get("/v1/jobs")
    async def list_jobs(limit: int = 200) -> list[dict[str, Any]]:
        return [normalize(j) for j in engine.list(limit=max(1, min(limit, 1000)))]

    async def submit_job(
        kind: str,
        params: dict[str, Any],
        key: str | None,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        job, created = await engine.submit_once(kind, params, cid(request), idempotency_key=key)
        response.status_code = 201 if created else 200  # 200: the earlier job for this key
        return normalize(job)

    @app.post("/v1/jobs", status_code=201)
    async def submit(body: SubmitJob, request: Request, response: Response) -> dict[str, Any]:
        return await submit_job(body.kind, body.params, body.idempotency_key, request, response)

    # -- imports and assets (M05) ------------------------------------------------------

    def read_assets(fn: Callable[[AssetRepository], Any]) -> Any:
        with contextlib.closing(engine.database.connect()) as conn:
            return fn(AssetRepository(conn))

    @app.post("/v1/imports", status_code=201)
    async def submit_import(
        body: SubmitImport, request: Request, response: Response
    ) -> dict[str, Any]:
        params = body.model_dump(exclude={"idempotency_key"})
        return await submit_job("import", params, body.idempotency_key, request, response)

    @app.get("/v1/imports/{job_id}")
    async def get_import(job_id: str) -> dict[str, Any]:
        job = engine.get(job_id)
        if job.kind != "import":
            raise EngineError("import.not_found", f"import {job_id} not found", status=404)
        return normalize(job)

    @app.get("/v1/assets")
    async def list_assets(
        missing: bool | None = None, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 1000))
        assets = await asyncio.to_thread(
            read_assets,
            lambda repo: repo.query(missing=missing, limit=bounded, offset=max(0, offset)),
        )
        return [normalize(a) for a in assets]

    @app.post("/v1/assets/check-sources", status_code=201)
    async def check_sources(request: Request, response: Response) -> dict[str, Any]:
        return await submit_job("check_sources", {}, None, request, response)

    @app.get("/v1/assets/{asset_id}")
    async def get_asset(asset_id: str) -> dict[str, Any]:
        try:
            asset = await asyncio.to_thread(read_assets, lambda repo: repo.get(asset_id))
        except NotFoundError as exc:
            raise EngineError("asset.not_found", f"asset {asset_id} not found", status=404) from exc
        return normalize(asset)

    @app.post("/v1/assets/{asset_id}/relink", status_code=201)
    async def relink(
        asset_id: str, body: SubmitRelink, request: Request, response: Response
    ) -> dict[str, Any]:
        params = {"asset_id": asset_id, "path": body.path}
        return await submit_job("relink", params, body.idempotency_key, request, response)

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        return normalize(engine.get(job_id))

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, Any]:
        return normalize(await engine.cancel(job_id))

    @app.post("/v1/jobs/{job_id}/retry")
    async def retry(job_id: str) -> dict[str, Any]:
        return normalize(await engine.retry(job_id))

    @app.post("/v1/shutdown", status_code=202)
    async def shutdown() -> dict[str, str]:
        asyncio.get_running_loop().call_soon(settings.on_shutdown_request)
        return {"status": "stopping"}

    @app.websocket("/v1/jobs/events")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        sub = engine.subscribe()

        async def drain_client() -> None:
            # Clients do not send messages; read only to notice disconnects.
            while True:
                await websocket.receive_text()

        reader = asyncio.create_task(drain_client())
        try:
            while True:
                getter = asyncio.create_task(sub.queue.get())
                done, _ = await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
                if reader in done:
                    getter.cancel()
                    break
                event = getter.result()
                if event is None:
                    code, reason = (1013, "resync") if sub.overflowed else (1001, "worker stopping")
                    await websocket.close(code=code, reason=reason)
                    break
                await websocket.send_text(json.dumps(normalize(event)))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader.cancel()
            engine.unsubscribe(sub)

    return Guard(app, settings)
