# Architecture

Architecture decisions are recorded as ADRs in [`adr/`](./adr/). Copy
[`adr/0000-template.md`](./adr/0000-template.md), take the next number, and
open it in the same pull request as the change it justifies.

| ADR | Title | Status |
|---|---|---|
| [0001](./adr/0001-multi-process-architecture.md) | Multi-process desktop architecture | Accepted |
| [0002](./adr/0002-contract-schemas-and-generation.md) | JSON Schema contracts with generated types | Accepted |
| [0003](./adr/0003-sqlite-migrations.md) | Standard-library SQLite with an in-house migration runner | Accepted |
| [0004](./adr/0004-worker-ipc.md) | Worker IPC: stdin token, loopback HTTP, WebSocket events | Accepted |

Other architecture notes:

- [Storage](./storage.md): what lives in SQLite vs on disk, delete policies, migrations, backups.
- [Worker lifecycle and jobs](./worker.md): process lifecycle, API, job handlers, cancellation, retry rules.
- [Media probing](./media.md): FFmpeg discovery and minimum version, `doctor`, the probe job, normalized metadata, error codes, fixtures.
- [Fingerprints and duplicates](./fingerprints.md): exact, fast, perceptual, and audio fingerprints, versioning, duplicate candidates, backfill.
- [Watched folders](./watched-folders.md): host watcher and stabilization, worker decisions, reconciliation, offline backoff, cloud placeholders, Xbox onboarding.
- [Desktop library and jobs UI](./desktop-ui.md): routes and components, the allow-listed `worker_api` bridge, the `owm-media` playback protocol, job center behavior, keyboard access, tests, player limitations.
- [Derived media](./derived-media.md): proxy policy and preset, deterministic HDR tone mapping, filmstrip thumbnails, waveform format, cache keys and invalidation, artifact layout, cleanup, minimum FFmpeg capabilities.
- [Safe import pipeline](./import.md): reference and managed imports, staging and atomic promotion, idempotency, provenance, missing sources and relink, error codes.
