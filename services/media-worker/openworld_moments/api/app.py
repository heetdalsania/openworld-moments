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
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openworld_moments_contracts import normalize
from openworld_moments_contracts.versioning import SUPPORTED_VERSION
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from openworld_moments import __version__
from openworld_moments.alignment.service import Aligner
from openworld_moments.derived.service import DerivedMedia, MediaUnavailable
from openworld_moments.detectors.calibration import Calibration
from openworld_moments.detectors.profiles import ProfileCatalog, ProfileError
from openworld_moments.fingerprints.service import candidate_doc, fingerprints_doc
from openworld_moments.ids import new_id
from openworld_moments.jobs.engine import EngineError, JobEngine
from openworld_moments.projects.service import (
    ImportProject,
    ManualProject,
    ProjectError,
    ProjectService,
    RelinkProject,
    SaveProject,
)
from openworld_moments.review.service import (
    EventReviewService,
    ManualEvent,
    ReviewChange,
    ReviewError,
)
from openworld_moments.sessions.service import SessionError, SessionService
from openworld_moments.storage import (
    AssetRepository,
    ConflictError,
    DuplicateCandidateRepository,
    EventRepository,
    NotFoundError,
    WatchedFolderRepository,
    transaction,
)
from openworld_moments.stories.service import StoryDecision, StoryError, StoryRequest, StoryService
from openworld_moments.transcripts.service import Transcriber
from openworld_moments.watched import service as watched

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


class SubmitDerived(BaseModel):
    """DerivedMediaRequest without asset_id (it is in the path), plus an idempotency key."""

    model_config = ConfigDict(extra="forbid")
    artifacts: list[Any] | None = None
    proxy_policy: str = "auto"
    force: bool = False
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class SubmitGroup(BaseModel):
    """GroupRequest plus an optional idempotency key."""

    model_config = ConfigDict(extra="forbid")
    max_gap_ms: int | None = None
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class MergeSessions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_ids: list[str] = Field(min_length=2, max_length=50)


class SplitSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_asset_id: str


class ReorderSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] = Field(min_length=1, max_length=10_000)


class RemoveFromSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str


class SubmitAlign(BaseModel):
    """AlignRequest plus an optional idempotency key. Params are checked by the handler."""

    model_config = ConfigDict(extra="forbid")
    session_ids: list[Any] | None = None
    force: bool = False
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class SubmitAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str
    locale: str | None = None
    force: bool = False
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class SubmitTranscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    language: str | None = None
    force: bool = False
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class SubmitStories(StoryRequest):
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class PreviewCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    regions: dict[str, Any] = Field(max_length=128)
    gray: list[Annotated[int, Field(strict=True, ge=0, le=255)]] = Field(
        min_length=2304, max_length=2304
    )
    source_ms: int = Field(ge=0, le=86400000)


class SaveCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    regions: dict[str, Any] = Field(max_length=128)


class SetOverlap(BaseModel):
    """OverlapOverride: an overlap in ms (0 = no overlap), or null to clear."""

    model_config = ConfigDict(extra="forbid")
    overlap_ms: int | None


class SubmitBackfill(BaseModel):
    """FingerprintRequest plus an optional idempotency key. Params are checked by the handler."""

    model_config = ConfigDict(extra="forbid")
    asset_ids: list[Any] | None = None
    force: bool = False
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY)


class ReviewDuplicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_state: Literal["unreviewed", "duplicate", "distinct"]


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
    derived: DerivedMedia | None = None,
    profile_catalog: ProfileCatalog | None = None,
    transcriber: Transcriber | None = None,
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
        missing: bool | None = None,
        limit: int = 200,
        offset: int = 0,
        order: Literal["oldest", "newest"] = "oldest",
        after: str | None = None,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 1000))
        try:
            assets = await asyncio.to_thread(
                read_assets,
                lambda repo: repo.query(
                    missing=missing,
                    limit=bounded,
                    offset=max(0, offset),
                    newest=order == "newest",
                    after=after,
                ),
            )
        except NotFoundError as exc:
            raise EngineError(
                "asset.not_found", "The 'after' asset does not exist.", status=404
            ) from exc
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

    # -- fingerprints and duplicates (M06) ---------------------------------------------

    def with_conn(fn: Callable[[Any], Any]) -> Any:
        with contextlib.closing(engine.database.connect()) as conn:
            return fn(conn)

    @app.get("/v1/assets/{asset_id}/fingerprints")
    async def get_fingerprints(asset_id: str) -> dict[str, Any]:
        try:
            doc: dict[str, Any] = await asyncio.to_thread(
                with_conn, lambda conn: fingerprints_doc(conn, asset_id)
            )
        except NotFoundError as exc:
            raise EngineError("asset.not_found", f"asset {asset_id} not found", status=404) from exc
        return doc

    @app.post("/v1/fingerprints/backfill", status_code=201)
    async def backfill(
        body: SubmitBackfill, request: Request, response: Response
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"force": body.force}
        if body.asset_ids is not None:
            params["asset_ids"] = body.asset_ids
        return await submit_job("fingerprint", params, body.idempotency_key, request, response)

    # -- derived media (M08) ------------------------------------------------------------

    def derived_service() -> DerivedMedia:
        if derived is None:
            raise EngineError("request.not_found", "Derived media is not available.", status=404)
        return derived

    @app.get("/v1/assets/{asset_id}/derived")
    async def get_derived(asset_id: str) -> dict[str, Any]:
        service = derived_service()
        try:
            doc: dict[str, Any] = await asyncio.to_thread(
                with_conn, lambda conn: service.status_doc(conn, asset_id)
            )
        except NotFoundError as exc:
            raise EngineError("asset.not_found", f"asset {asset_id} not found", status=404) from exc
        return doc

    @app.post("/v1/assets/{asset_id}/derived", status_code=201)
    async def submit_derived(
        asset_id: str, body: SubmitDerived, request: Request, response: Response
    ) -> dict[str, Any]:
        derived_service()
        params: dict[str, Any] = {
            "asset_id": asset_id,
            "proxy_policy": body.proxy_policy,
            "force": body.force,
        }
        if body.artifacts is not None:
            params["artifacts"] = body.artifacts
        return await submit_job("proxy", params, body.idempotency_key, request, response)

    @app.get("/v1/assets/{asset_id}/media/{variant}")
    async def media_file(asset_id: str, variant: str, index: int | None = None) -> dict[str, Any]:
        """Host only (the UI cannot reach it): the checked local path of an asset's
        original, proxy, thumbnail, or waveform for the host's media protocol."""
        service = derived_service()
        try:
            found: dict[str, Any] = await asyncio.to_thread(
                with_conn, lambda conn: service.media_file(conn, asset_id, variant, index)
            )
        except NotFoundError as exc:
            raise EngineError("asset.not_found", f"asset {asset_id} not found", status=404) from exc
        except MediaUnavailable as exc:
            raise EngineError(exc.code, exc.message, status=404) from exc
        return found

    @app.post("/v1/derived/cleanup")
    async def cleanup_derived() -> dict[str, Any]:
        service = derived_service()
        return await asyncio.to_thread(service.cleanup)

    # -- calibration (M15): JSON data only, no paths or media in patches ----------------
    calibration = Calibration(engine.database, profile_catalog)

    @app.exception_handler(ProfileError)
    async def profile_error(request: Request, exc: ProfileError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, correlation_id=cid(request)), status_code=422
        )

    @app.get("/v1/profiles")
    async def list_profiles() -> list[dict[str, Any]]:
        return await asyncio.to_thread(calibration.list_profiles)

    @app.get("/v1/profiles/{profile_id}/calibration")
    async def get_calibration(profile_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(calibration.state, profile_id)

    @app.put("/v1/profiles/{profile_id}/calibration")
    async def save_calibration(profile_id: str, body: SaveCalibration) -> dict[str, Any]:
        return await asyncio.to_thread(calibration.save, profile_id, body.base_key, body.regions)

    @app.post("/v1/profiles/{profile_id}/patch")
    async def import_profile_patch(profile_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(calibration.import_patch, profile_id, body)

    @app.post("/v1/profiles/{profile_id}/preview")
    async def preview_calibration(profile_id: str, body: PreviewCalibration) -> dict[str, Any]:
        return await asyncio.to_thread(
            calibration.preview, profile_id, body.base_key, body.regions, body.gray, body.source_ms
        )

    @app.post("/v1/profiles/{profile_id}/reset")
    async def reset_calibration(profile_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(calibration.reset, profile_id)

    # -- sessions (M11) -----------------------------------------------------------------

    @app.post("/v1/sessions/{session_id}/analyze", status_code=201)
    async def analyze_session(
        session_id: str, body: SubmitAnalysis, request: Request, response: Response
    ) -> dict[str, Any]:
        params = body.model_dump(exclude={"idempotency_key"}, exclude_none=True)
        params["session_id"] = session_id
        return await submit_job("analyze", params, body.idempotency_key, request, response)

    # -- transcription (M18) ---------------------------------------------------------------

    def speech() -> Transcriber:
        nonlocal transcriber
        if transcriber is None:
            media = derived_service()
            transcriber = Transcriber(engine.database, media.tools, media)
        return transcriber

    def session_missing(sid: str) -> EngineError:
        return EngineError("session.not_found", f"session {sid} not found", status=404)

    @app.get("/v1/transcription/models")
    async def transcription_models() -> dict[str, Any]:
        return await asyncio.to_thread(speech().status)

    @app.post("/v1/sessions/{session_id}/transcribe", status_code=201)
    async def transcribe_session(
        session_id: str, body: SubmitTranscription, request: Request, response: Response
    ) -> dict[str, Any]:
        params = body.model_dump(exclude={"idempotency_key"}, exclude_none=True)
        params["session_id"] = session_id
        return await submit_job("transcribe", params, body.idempotency_key, request, response)

    @app.get("/v1/sessions/{session_id}/transcript")
    async def get_transcript(session_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(speech().transcript, session_id)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    @app.delete("/v1/sessions/{session_id}/transcript")
    async def delete_transcript(session_id: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(speech().delete, session_id)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc
        return dict(result)

    projects = ProjectService(engine.database)

    @app.exception_handler(ProjectError)
    async def project_error(request: Request, exc: ProjectError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, correlation_id=cid(request)), status_code=exc.status
        )

    def project_missing() -> ProjectError:
        return ProjectError("project.not_found", "Project or selected source not found.", 404)

    @app.get("/v1/projects")
    async def list_projects(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100000),
    ) -> dict[str, Any]:
        return await asyncio.to_thread(projects.page, limit=limit, offset=offset)

    @app.get("/v1/sessions/{session_id}/project-selection")
    async def project_selection(session_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.selection, session_id)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    @app.get("/v1/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.get, project_id)
        except NotFoundError as exc:
            raise project_missing() from exc

    @app.put("/v1/projects/{project_id}")
    async def save_project(project_id: str, body: SaveProject) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.save, project_id, body)
        except NotFoundError as exc:
            raise project_missing() from exc

    @app.post("/v1/projects/{project_id}/relink")
    async def relink_project(project_id: str, body: RelinkProject) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.relink, project_id, body)
        except NotFoundError as exc:
            raise project_missing() from exc

    @app.get("/v1/projects/{project_id}/portable")
    async def export_project(project_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.export, project_id)
        except NotFoundError as exc:
            raise project_missing() from exc

    @app.post("/v1/projects/import", status_code=201)
    async def import_project(body: ImportProject) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.import_document, body)
        except NotFoundError as exc:
            raise project_missing() from exc

    @app.post("/v1/sessions/{session_id}/projects", status_code=201)
    async def manual_project(session_id: str, body: ManualProject) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(projects.create, session_id, body)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    stories = StoryService(engine.database)

    @app.exception_handler(StoryError)
    async def story_error(request: Request, exc: StoryError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, retryable=False, correlation_id=cid(request)),
            status_code=exc.status,
        )

    @app.post("/v1/sessions/{session_id}/stories", status_code=201)
    async def generate_stories(
        session_id: str, body: SubmitStories, request: Request, response: Response
    ) -> dict[str, Any]:
        params = body.model_dump(exclude={"idempotency_key"}, exclude_none=True)
        params["session_id"] = session_id
        return await submit_job("story", params, body.idempotency_key, request, response)

    @app.get("/v1/sessions/{session_id}/stories")
    async def list_stories(
        session_id: str,
        preset: Literal["moment", "short", "extended_short", "highlight"] = "short",
        pre_roll_ms: int | None = Query(default=None, ge=0, le=60000),
        post_roll_ms: int | None = Query(default=None, ge=0, le=60000),
        merge_gap_ms: int | None = Query(default=None, ge=0, le=30000),
        avoid_spoilers: bool = False,
        allow_unreviewed: bool = True,
        include_history: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        options = StoryRequest(
            preset=preset,
            pre_roll_ms=pre_roll_ms,
            post_roll_ms=post_roll_ms,
            merge_gap_ms=merge_gap_ms,
            avoid_spoilers=avoid_spoilers,
            allow_unreviewed=allow_unreviewed,
        )
        try:
            return await asyncio.to_thread(
                stories.page,
                session_id,
                options,
                include_history=include_history,
                offset=offset,
                limit=limit,
            )
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    @app.post("/v1/sessions/{session_id}/stories/{candidate_id}/decision")
    async def decide_story(
        session_id: str, candidate_id: str, body: StoryDecision
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(stories.decide, session_id, candidate_id, body)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    review = EventReviewService(engine.database)

    @app.exception_handler(ReviewError)
    async def review_error(request: Request, exc: ReviewError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, retryable=False, correlation_id=cid(request)),
            status_code=exc.status,
        )

    @app.get("/v1/sessions/{session_id}/review")
    async def review_events(session_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(review.page, session_id, offset, limit)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    @app.post("/v1/sessions/{session_id}/review", status_code=201)
    async def manual_event(session_id: str, body: ManualEvent) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(review.manual, session_id, body)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    @app.post("/v1/sessions/{session_id}/review/{event_id}")
    async def review_event(session_id: str, event_id: str, body: ReviewChange) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(review.change, session_id, event_id, body)
        except NotFoundError as exc:
            raise session_missing(session_id) from exc

    @app.get("/v1/events")
    async def list_events(
        session_id: str, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        # Pagination is bounded at the repository query, not after loading all events.
        rows = await asyncio.to_thread(
            with_conn,
            lambda conn: EventRepository(conn).page_for_session(
                session_id, limit=max(1, min(limit, 1000)), offset=max(0, offset)
            ),
        )
        return [normalize(event) for event in rows]

    session_service = SessionService(engine.database)

    @app.exception_handler(SessionError)
    async def session_error(request: Request, exc: SessionError) -> JSONResponse:
        body = error_body(exc.code, exc.message, retryable=False, correlation_id=cid(request))
        return JSONResponse(body, status_code=exc.status)

    @app.get("/v1/sessions")
    async def list_sessions(limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 1000))
        docs: list[dict[str, Any]] = await asyncio.to_thread(
            with_conn,
            lambda conn: session_service.list_docs(conn, limit=bounded, offset=max(0, offset)),
        )
        return docs

    @app.post("/v1/sessions/recompute", status_code=201)
    async def recompute_sessions(
        body: SubmitGroup, request: Request, response: Response
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if body.max_gap_ms is not None:
            params["max_gap_ms"] = body.max_gap_ms
        return await submit_job("group", params, body.idempotency_key, request, response)

    aligner = Aligner(engine.database)

    @app.post("/v1/sessions/align", status_code=201)
    async def align_sessions(
        body: SubmitAlign, request: Request, response: Response
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"force": body.force}
        if body.session_ids is not None:
            params["session_ids"] = body.session_ids
        return await submit_job("align", params, body.idempotency_key, request, response)

    @app.get("/v1/sessions/{session_id}/overlaps")
    async def session_overlaps(session_id: str) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = await asyncio.to_thread(
            with_conn, lambda conn: aligner.overlaps_doc(conn, session_id)
        )
        return docs

    @app.put("/v1/sessions/{session_id}/overlaps/{asset_id}")
    async def set_overlap(session_id: str, asset_id: str, body: SetOverlap) -> dict[str, Any]:
        doc: dict[str, Any] = await asyncio.to_thread(
            aligner.set_override, session_id, asset_id, body.overlap_ms
        )
        return doc

    @app.post("/v1/sessions/merge")
    async def merge_sessions(body: MergeSessions) -> dict[str, Any]:
        doc: dict[str, Any] = await asyncio.to_thread(session_service.merge, body.session_ids)
        return doc

    @app.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        doc: dict[str, Any] = await asyncio.to_thread(
            with_conn, lambda conn: session_service.doc(conn, session_id)
        )
        return doc

    @app.get("/v1/sessions/{session_id}/corrections")
    async def session_corrections(session_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = await asyncio.to_thread(
            with_conn, lambda conn: session_service.corrections(conn, session_id)
        )
        return rows

    @app.post("/v1/sessions/{session_id}/split")
    async def split_session(session_id: str, body: SplitSession) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = await asyncio.to_thread(
            session_service.split, session_id, body.after_asset_id
        )
        return docs

    @app.post("/v1/sessions/{session_id}/order")
    async def reorder_session(session_id: str, body: ReorderSession) -> dict[str, Any]:
        doc: dict[str, Any] = await asyncio.to_thread(
            session_service.reorder, session_id, body.asset_ids
        )
        return doc

    @app.post("/v1/sessions/{session_id}/remove")
    async def remove_from_session(session_id: str, body: RemoveFromSession) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = await asyncio.to_thread(
            session_service.remove, session_id, body.asset_id
        )
        return docs

    @app.post("/v1/sessions/{session_id}/confirm")
    async def confirm_session(session_id: str) -> dict[str, Any]:
        doc: dict[str, Any] = await asyncio.to_thread(session_service.confirm, session_id)
        return doc

    @app.get("/v1/duplicates")
    async def list_duplicates(
        review_state: Literal["unreviewed", "duplicate", "distinct"] | None = None,
        asset_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            with_conn,
            lambda conn: DuplicateCandidateRepository(conn).query(
                review_state=review_state,
                asset_id=asset_id,
                limit=max(1, min(limit, 1000)),
                offset=max(0, offset),
            ),
        )
        return [candidate_doc(r) for r in rows]

    @app.get("/v1/duplicates/{candidate_id}")
    async def get_duplicate(candidate_id: int) -> dict[str, Any]:
        try:
            row = await asyncio.to_thread(
                with_conn, lambda conn: DuplicateCandidateRepository(conn).get(candidate_id)
            )
        except NotFoundError as exc:
            raise EngineError(
                "duplicate.not_found", f"duplicate candidate {candidate_id} not found", status=404
            ) from exc
        return candidate_doc(row)

    @app.patch("/v1/duplicates/{candidate_id}")
    async def review_duplicate(candidate_id: int, body: ReviewDuplicate) -> dict[str, Any]:
        """Record a person's decision. Never merges or deletes anything."""

        def update(conn: Any) -> Any:
            with transaction(conn):
                return DuplicateCandidateRepository(conn).set_review_state(
                    candidate_id, body.review_state
                )

        try:
            row = await asyncio.to_thread(with_conn, update)
        except NotFoundError as exc:
            raise EngineError(
                "duplicate.not_found", f"duplicate candidate {candidate_id} not found", status=404
            ) from exc
        return candidate_doc(row)

    # -- watched folders (M07) ----------------------------------------------------------

    @app.exception_handler(watched.WatchError)
    async def watch_error(request: Request, exc: watched.WatchError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, correlation_id=cid(request)), status_code=exc.status
        )

    def folder_or_404(conn: Any, folder_id: int) -> Any:
        try:
            return WatchedFolderRepository(conn).get(folder_id)
        except NotFoundError as exc:
            raise watched.WatchError(
                "watch.folder_not_found", f"watched folder {folder_id} not found", status=404
            ) from exc

    @app.get("/v1/watched-folders")
    async def list_watched() -> list[dict[str, Any]]:
        def read(conn: Any) -> list[dict[str, Any]]:
            return [watched.folder_doc(conn, f) for f in WatchedFolderRepository(conn).all()]

        result: list[dict[str, Any]] = await asyncio.to_thread(with_conn, read)
        return result

    @app.post("/v1/watched-folders", status_code=201)
    async def add_watched(body: dict[str, Any]) -> dict[str, Any]:
        clean = watched.validate_changes(body, creating=True)

        def create(conn: Any) -> dict[str, Any]:
            with transaction(conn):
                try:
                    row = WatchedFolderRepository(conn).create(**clean)
                except ConflictError as exc:
                    raise watched.WatchError(
                        "watch.already_watched", "This folder is already watched.", status=409
                    ) from exc
            return watched.folder_doc(conn, row)

        result: dict[str, Any] = await asyncio.to_thread(with_conn, create)
        return result

    @app.get("/v1/watched-folders/{folder_id}")
    async def get_watched(folder_id: int) -> dict[str, Any]:
        result: dict[str, Any] = await asyncio.to_thread(
            with_conn, lambda conn: watched.folder_doc(conn, folder_or_404(conn, folder_id))
        )
        return result

    @app.patch("/v1/watched-folders/{folder_id}")
    async def change_watched(folder_id: int, body: dict[str, Any]) -> dict[str, Any]:
        changes = watched.validate_changes(body, creating=False)

        def update(conn: Any) -> dict[str, Any]:
            folder_or_404(conn, folder_id)
            with transaction(conn):
                row = (
                    WatchedFolderRepository(conn).update(folder_id, changes)
                    if changes
                    else (WatchedFolderRepository(conn).get(folder_id))
                )
            return watched.folder_doc(conn, row)

        result: dict[str, Any] = await asyncio.to_thread(with_conn, update)
        return result

    @app.delete("/v1/watched-folders/{folder_id}", status_code=204)
    async def remove_watched(folder_id: int) -> Response:
        """Stops watching. The folder and its files on disk are never touched."""

        def delete(conn: Any) -> None:
            folder_or_404(conn, folder_id)
            with transaction(conn):
                WatchedFolderRepository(conn).delete(folder_id)

        await asyncio.to_thread(with_conn, delete)
        return Response(status_code=204)

    @app.post("/v1/watched-folders/{folder_id}/scans")
    async def report_scan(folder_id: int, body: dict[str, Any]) -> dict[str, Any]:
        available, scanned, error = watched.scan_error(body)

        def record(conn: Any) -> dict[str, Any]:
            folder_or_404(conn, folder_id)
            with transaction(conn):
                row = WatchedFolderRepository(conn).record_scan(
                    folder_id, available=available, scanned=scanned, error=error
                )
            return watched.folder_doc(conn, row)

        result: dict[str, Any] = await asyncio.to_thread(with_conn, record)
        return result

    @app.get("/v1/watched-folders/{folder_id}/files")
    async def watched_files(
        folder_id: int, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        def read(conn: Any) -> list[dict[str, Any]]:
            folder_or_404(conn, folder_id)
            rows = WatchedFolderRepository(conn).files(
                folder_id, limit=max(1, min(limit, 1000)), offset=max(0, offset)
            )
            return [watched.file_doc(conn, r) for r in rows]

        result: list[dict[str, Any]] = await asyncio.to_thread(with_conn, read)
        return result

    @app.post("/v1/watched-folders/{folder_id}/files")
    async def report_file(folder_id: int, body: dict[str, Any], request: Request) -> dict[str, Any]:
        """A stable file reported by the host: import it unless this version is known."""
        rel, size, mtime = watched.validate_report(body)

        def check(conn: Any) -> tuple[Any, int | None, dict[str, Any]]:
            folder = folder_or_404(conn, folder_id)
            attempt, decision = watched.decide(conn, folder, rel, size, mtime)
            return folder, attempt, decision

        checked: tuple[Any, int | None, dict[str, Any]] = await asyncio.to_thread(with_conn, check)
        folder, attempt, decision = checked
        if attempt is None:
            return decision
        job, _ = await engine.submit_once(
            "import",
            watched.import_params(folder, rel),
            cid(request),
            idempotency_key=watched.idempotency_key(folder_id, rel, size, mtime, attempt),
        )

        def record(conn: Any) -> dict[str, Any]:
            with transaction(conn):
                return watched.record_submission(conn, folder, rel, size, mtime, attempt, job.id)

        result: dict[str, Any] = await asyncio.to_thread(with_conn, record)
        return result

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
