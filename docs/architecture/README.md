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
