# ADR-0004: Worker IPC: stdin token, loopback HTTP, WebSocket events

- Status: Accepted
- Date: 2026-11-05
- Milestone: M03
- Deciders: project maintainers

## Context

ADR-0001 places media work in a Python worker that the Rust host supervises
over a token-authenticated loopback API (spec §9.2.1, §9.4). M03 must choose
how the token reaches the worker, how readiness and the port are discovered,
and how progress is streamed, while keeping secrets out of logs (spec §14).

## Decision

- **Token delivery: stdin.** The host generates 32 random bytes per launch and
  writes them hex-encoded as the first line of the worker's stdin. Unlike an
  environment variable, stdin is not visible in process listings and is not
  inherited by the worker's own child processes (FFmpeg later).
- **stdin as a lifeline.** The host keeps stdin open. EOF means "shut down", so a
  worker whose host died exits on its own instead of lingering.
- **Readiness and discovery: one stdout line.** The worker binds
  `127.0.0.1:0`, opens and migrates the library database, starts the job engine,
  then prints exactly one JSON line, either `{"event":"ready","port":...}` or
  `{"event":"error","code":...}`. stdout carries nothing else; logs are JSON on
  stderr.
- **Transport: HTTP on loopback (FastAPI + uvicorn), progress over WebSocket**
  at `/v1/jobs/events`, as spec §9.4 names. Each event carries a per-process
  `seq` (contract `JobEvent`); gaps or a reconnect mean "resynchronize with
  `GET /v1/jobs`".
- **Request guard on every HTTP and WebSocket request:** loopback peer only,
  `Host` must be the bound loopback address (blocks DNS rebinding from a
  browser), and the bearer token is compared in constant time. Rejections
  use the `ErrorInfo` contract. No CORS, no OpenAPI or docs routes.
- **Durable jobs** in SQLite with cooperative cancellation via a per-job event
  checked by handlers; crash recovery requeues idempotent jobs or fails the rest
  with a retryable `job.interrupted` error.

## Consequences

- Only the host can talk to the worker; the UI goes through Tauri commands.
- Restarting the worker changes its port and token; clients get both from the
  supervisor, never from disk.
- Long-lived WebSocket subscribers get a bounded queue; a slow subscriber is
  disconnected with close code 1013 ("resync") rather than slowing the engine.
- The phone upload gateway (M10) remains a separate listener (spec §9.2.2).

## Alternatives considered

- **Token in an environment variable:** simpler, but visible to same-user
  process inspection and inherited by tool subprocesses unless scrubbed.
- **Server-sent events:** one-way and simpler, but spec §9.4 already names a
  WebSocket, and the host's Rust client handles both equally.
- **Named pipes / Unix sockets instead of TCP:** stronger isolation, but
  platform-specific (named pipes on Windows, sockets elsewhere) and awkward for
  the existing HTTP tooling. Can be revisited behind the same API.
- **gRPC:** heavier toolchain on both sides for no MVP benefit.
