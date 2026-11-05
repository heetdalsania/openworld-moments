# M03 — Worker lifecycle and job engine

## Objective

Create authenticated local communication between the desktop host and Python worker, plus a durable cancellable job engine for all later background work.

## Dependencies

M02 merged.

## Required context

Read specification sections 9.2, 9.4, 9.5, 14.1, and 14.2.

## In scope

- Worker process startup, health, restart, and shutdown.
- Loopback-only FastAPI service on an ephemeral port.
- Per-launch bearer token passed without writing it to logs.
- Durable queued/running/completed/failed/cancelled job states.
- Progress events over WebSocket or server-sent events as recorded in an ADR.
- Cooperative cancellation and crash recovery.
- Structured error contract and correlation IDs.

## Out of scope

- Product-specific job handlers, LAN binding, and automatic updates.

## Implementation steps

1. Implement Rust worker supervisor and readiness handshake.
2. Implement token authentication and loopback binding assertion.
3. Implement job repository, runner, progress publisher, and cancellation token.
4. Add a synthetic long-running job for UI/integration tests.
5. Requeue or mark interrupted jobs according to retryability on restart.
6. Add bounded stderr capture and redaction.
7. Document API lifecycle and failure semantics.

## Acceptance criteria

- Unauthenticated requests are rejected.
- Service is not reachable through a non-loopback interface.
- Cancelling the synthetic job reaches `cancelled` and stops work.
- Worker crash is detected; restart preserves durable job records.
- UI receives ordered progress with correlation IDs.
- Tokens and environment secrets do not appear in logs.

## Required validation

- Supervisor integration tests.
- Authentication tests.
- Cancellation, crash, restart, and retry tests.
- Port-conflict and malformed-event tests.

## Handoff

Document process lifecycle, API base discovery, job handler interface, cancellation contract, and retry rules. Update M03.

