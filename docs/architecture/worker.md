# Worker lifecycle and jobs

Implemented in M03. Decision record: [ADR-0004](./adr/0004-worker-ipc.md).
Code: `apps/desktop/src-tauri/src/worker/` (Rust supervisor) and
`services/media-worker/openworld_moments/{worker,api,jobs}/` (Python).

## Process lifecycle

```text
Stopped → Starting → Ready ⇄ Restarting → (Ready | Failed)
                 ↘ Failed (startup error)
```

1. **Spawn.** The host runs `python -m openworld_moments.worker --library <dir>`
   with stdin, stdout, and stderr piped.
2. **Token.** The host writes a fresh 64-hex-character token plus newline to
   stdin and keeps stdin open.
3. **Handshake.** The worker binds `127.0.0.1` on an ephemeral port, migrates
   `<library>/database.sqlite3`, starts the job engine, and prints one line:
   - `{"event":"ready","protocol":1,"api_version":1,"schema_version":"1.1","worker_version":"…","host":"127.0.0.1","port":N,"pid":P}`
   - or `{"event":"error","code":"…","message":"…"}` and exit code 3.
   The host waits up to 30 s (`ready_timeout`).
4. **Running.** The host captures the last 8 KB of stderr (redacted) for error
   reports. A monitor task waits for the process to exit.
5. **Stop.** The host closes stdin. The worker stops accepting jobs, interrupts
   running handlers, and exits 0. After `shutdown_timeout` (10 s) the host kills it.
   `POST /v1/shutdown` does the same from the API side.
6. **Crash.** Any exit the host did not ask for is a crash. The host restarts the
   worker after 250 ms, 500 ms, 1 s, … up to `max_restarts` (3) within
   `restart_window` (60 s), then reports `Failed` with code `worker.crash_loop`
   and the stderr tail.

The UI sees every status change as the `worker://status` event and through the
`worker_status` command.

### Startup error codes

| Code | Meaning |
|---|---|
| `worker.missing_token` | No valid token line on stdin |
| `worker.non_loopback_host` | `--host` was not a loopback address |
| `worker.port_in_use` | `--port` was given and is taken (the default port 0 never conflicts) |
| `worker.bind_failed` | Any other bind failure |
| `worker.database_error` | The library database could not be opened or migrated |
| `worker.exited` | Process exited before the handshake (host-side; stderr tail attached) |
| `worker.ready_timeout` | No handshake within `ready_timeout` (host-side) |
| `worker.protocol_mismatch` | Malformed handshake, unexpected protocol, or non-loopback host (host-side) |
| `worker.spawn_failed` | The program could not be started (host-side) |

## API base discovery and authentication

Base URL: `http://127.0.0.1:<port>` from the handshake. Port and token change on
every (re)start, and only the supervisor knows them; nothing is written to disk.

Every request, HTTP or WebSocket, needs:

- a loopback peer (`auth.non_loopback_peer`, 403),
- `Host: 127.0.0.1:<port>` (`auth.bad_host`, 403),
- `Authorization: Bearer <token>` (`auth.missing_token` / `auth.invalid_token`, 401).

Optional `X-Correlation-Id: cor_<ULID>` is echoed back. If it is missing or
invalid, the worker generates one. Jobs record the correlation ID of the request
that created them, and every event and log line for that job carries it.

## Endpoints (API v1)

| Method | Path | Result |
|---|---|---|
| GET | `/v1/health` | `{status, api_version, schema_version, worker_version, pid}` |
| GET | `/v1/capabilities?refresh=bool` | Media tool report, same as `doctor --json` (see [media](./media.md)) |
| POST | `/v1/diagnostics` | M31 support report `{include_messages, host?}` → `{report, content, filename}`: a `diagnostics-report` (1.25) with versions, system check, library counts, job totals and recent failure codes; no footage, names, paths or tokens; messages only on opt-in, redacted. `content` is the exact text previewed and saved (the host saves it through `diagnostics_export`). M33: the desktop host adds `host`, its `platform-capabilities` report; a malformed one is left out |
| GET | `/v1/jobs?limit=N` | Newest jobs (contract `Job[]`) |
| POST | `/v1/jobs` | `{kind, params, idempotency_key?}` → 201 `Job` (state `queued`), or 200 with the earlier job for the same key |
| GET | `/v1/jobs/{id}` | `Job` |
| POST | `/v1/jobs/{id}/cancel` | `Job` (see cancellation) |
| POST | `/v1/jobs/{id}/retry` | `Job` back in `queued` |
| POST | `/v1/imports` | Import request → `Job` (kind `import`); see [import](./import.md) |
| GET | `/v1/imports/{id}` | Import `Job` with its `ImportResult` |
| GET | `/v1/assets?missing=bool&order=oldest\|newest&after=<asset-id>&limit=N` | `MediaAsset[]`. `after` is a keyset cursor (stable while new assets arrive); unknown cursor → 404 |
| GET | `/v1/assets/{id}` | `MediaAsset` |
| POST | `/v1/assets/{id}/relink` | `{path}` → `Job` (kind `relink`) |
| POST | `/v1/assets/check-sources` | → `Job` (kind `check_sources`) |
| GET | `/v1/assets/{id}/fingerprints` | `AssetFingerprints`; see [fingerprints](./fingerprints.md) |
| GET | `/v1/duplicates?review_state=&asset_id=` | `DuplicateCandidate[]` |
| GET | `/v1/duplicates/{id}` | `DuplicateCandidate` |
| PATCH | `/v1/duplicates/{id}` | `{review_state}` → `DuplicateCandidate` (never deletes) |
| POST | `/v1/fingerprints/backfill` | `{asset_ids?, force?}` → `Job` (kind `fingerprint`) |
| GET | `/v1/assets/{id}/derived` | `AssetDerivedMedia`: proxy decision and artifact states; see [derived media](./derived-media.md) |
| POST | `/v1/assets/{id}/derived` | `{artifacts?, proxy_policy?, force?, idempotency_key?}` → `Job` (kind `proxy`) |
| GET | `/v1/assets/{id}/media/{original\|proxy\|thumbnail\|waveform}?index=n` | **Host only** (not reachable from the UI): `{path, content_type, size_bytes}` of a checked file for the `owm-media` protocol; `media.source_missing`, `derived.not_ready`, `media.unknown_variant` (404). See [desktop UI](./desktop-ui.md) |
| POST | `/v1/sessions/{id}/analyze` | `{profile_id, locale?, force?, idempotency_key?}` → `Job` (kind `analyze`); see [detectors](./detectors.md) |
| GET | `/v1/events?session_id=&limit=&offset=` | Persisted `Event[]` snapshots with provenance; no review mutations in M14 |
| GET | `/v1/sessions?limit&offset` | `Session[]`, newest first; see [sessions](./sessions.md) |
| GET | `/v1/sessions/{id}` | `Session` |
| GET | `/v1/sessions/{id}/corrections` | `SessionCorrection[]` |
| POST | `/v1/sessions/recompute` | `{max_gap_ms?, idempotency_key?}` → `Job` (kind `group`) |
| POST | `/v1/sessions/align` | `{session_ids?, force?, idempotency_key?}` → `Job` (kind `align`); see [overlap](./overlap.md) |
| GET | `/v1/sessions/{id}/overlaps` | `AssetOverlap[]` for each adjacent pair |
| PUT | `/v1/sessions/{id}/overlaps/{asset_id}` | `{overlap_ms}` (0 = no overlap, null = clear) → `Session` |
| POST | `/v1/sessions/merge` | `{session_ids}` → merged `Session` (corrected) |
| POST | `/v1/sessions/{id}/split` | `{after_asset_id}` → `[Session, Session]` |
| POST | `/v1/sessions/{id}/order` | `{asset_ids}` → `Session` |
| POST | `/v1/sessions/{id}/remove` | `{asset_id}` → `[Session, Session]` (the clip alone, never regrouped) |
| POST | `/v1/sessions/{id}/confirm` | `Session` (confirmed, locked) |
| POST | `/v1/derived/cleanup` | `DerivedCleanupResult` (removes only unreferenced files in `derived/`) |
| GET / POST | `/v1/watched-folders` | `WatchedFolder[]` / create; see [watched folders](./watched-folders.md) |
| GET / PATCH / DELETE | `/v1/watched-folders/{id}` | Read, change, stop watching (files untouched) |
| GET / POST | `/v1/watched-folders/{id}/files` | `WatchedFile[]` / host report of a stable file → `WatchedFileDecision` |
| POST | `/v1/watched-folders/{id}/scans` | Host availability and scan report → `WatchedFolder` |
| POST | `/v1/shutdown` | 202, then graceful stop |
| WS | `/v1/jobs/events` | Stream of contract `JobEvent` JSON text frames |

Errors always use contract `ErrorInfo` (`code`, `message`, `retryable`,
`correlation_id`): `request.invalid` / `job.invalid_params` / `job.unknown_kind`
/ `job.invalid_idempotency_key` (422), `job.not_found` / `request.not_found` /
`import.not_found` / `asset.not_found` / `duplicate.not_found` /
`watch.folder_not_found` (404), `watch.*` (see [watched folders](./watched-folders.md#error-codes)), `derived.*` job errors (see [derived media](./derived-media.md#error-codes)), `session.not_found` (404) / `session.invalid_request` (422) / `session.in_use` (409), `job.not_cancellable` /
`job.not_retryable` / `job.max_attempts` / `job.idempotency_conflict` (409),
`worker.stopping` (503).

### Event stream

- Frames are `JobEvent` documents: `{schema_version, seq, emitted_at, kind, job}`.
  `kind` is `state` (state changed) or `progress` (progress or message changed).
- `seq` increases by exactly 1 per event within one worker process. The host's
  `SeqTracker` reports `InOrder`, `Gap` (missed events: refetch `GET /v1/jobs`),
  or `Stale` (drop it).
- After any reconnect or worker restart, refetch `GET /v1/jobs`; `seq` restarts
  at 1 in a new process.
- The host skips malformed frames, counts them, and keeps the connection open.
- If a subscriber falls 1000 events behind, the worker closes it with code 1013
  (`resync`). On shutdown it closes with 1001.

## Job handler interface (Python)

```python
from openworld_moments.jobs.engine import JobContext, JobFailure, JobHandler

def run(ctx: JobContext) -> dict | None:
    ctx.set_state("probing")           # optional: move between active stages
    for i, item in enumerate(items):
        ctx.check_cancelled()          # or ctx.sleep(seconds), which wakes on cancel
        ...
        ctx.progress(i + 1, len(items), "Probing files")
    if problem:
        raise JobFailure("media.probe_failed", "Explain it plainly.", retryable=True,
                         details={"reason": "..."}, stderr_tail=redacted_tail)
    return {"summary": ...}            # optional: stored as the job's `result`

HANDLER = JobHandler(
    kind="import",                     # must be a contract Job kind
    run=run,                           # runs in a worker thread
    validate=lambda params: {...},     # raise ValueError for bad params (→ 422)
    first_state="probing",             # active state entered when the job starts
    requeue_on_interrupt=False,        # True only if running twice is safe
    max_attempts=3,
)
```

Register handlers in `openworld_moments/jobs/handlers.py`
(`build_handlers`). Handlers must not log secrets, full paths, or media
content, and must not touch the database connection the engine owns.

Return normally → `ready`, with the returned JSON object (if any) stored as
`result`. `JobFailure` → `failed` with that error, including optional scalar
`details` and a redacted `stderr_tail` (capped at 8 KB); a `JobFailure(result=...)`
also stores that result (an import's per-file report). Any other
exception → `failed` with `job.handler_crashed` (not retryable); details go to
the redacted log only.

## Cancellation contract

- `queued` job: cancelled immediately (`state = cancelled`).
- Running job: the request sets the job's cancel flag and returns the job
  unchanged. The handler stops at its next `check_cancelled()` or `sleep()`, and
  the engine records `cancelled` with an event.
- Already `cancelled`: returns the job (idempotent). `ready` or `failed`: 409
  `job.not_cancellable`.
- Handlers should check at least every few hundred milliseconds of work.
  Subprocesses started by handlers must be terminated when cancellation is
  observed: pass `ctx.cancel_event` to `openworld_moments.media.process.run_tool`,
  which kills and reaps the tool within one poll interval (50 ms).

## Retry and crash-recovery rules

| Situation | Result |
|---|---|
| Handler raises `JobFailure(retryable=True)` | `failed`; `POST /retry` queues it again with `attempt + 1` |
| Retry beyond `max_attempts` | 409 `job.max_attempts` |
| Failure not retryable, or job not `failed` | 409 `job.not_retryable` |
| Worker stopped or crashed while a job was active, handler has `requeue_on_interrupt` and `attempt < max_attempts` | On next start: `queued`, `attempt + 1`, runs again |
| Same, otherwise | On next start: `failed` with `job.interrupted` (retryable) |
| `queued` jobs at stop or crash | Stay queued and run after restart |

All transitions are written to SQLite before they are published, so a crash
can lose at most in-flight progress, never a job record. If the system clock
moved backwards, `started_at` and `finished_at` are clamped so they never
precede earlier timestamps.

## Logging and redaction

- Worker logs are JSON lines on stderr. uvicorn access logs are disabled.
  Python warnings are routed through the logger.
- The token is registered with the log redactor before anything is logged.
  Bearer values and absolute user paths are replaced in every record.
- The host's stderr tail redacts the token and bearer values too, and the
  `Token` type never prints its value.
- Environment variables are never logged.

## Synthetic job

`kind: "diagnostic"`, params `{steps: 1..10000 (10), step_ms: 0..60000 (100),
fail_at?: 1..steps}`. It reports progress every step, honors cancellation,
fails retryably at `fail_at`, and is requeued after a crash. The UI and the
integration tests use it.
