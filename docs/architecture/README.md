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
| [0005](./adr/0005-local-ocr.md) | Local region OCR with Tesseract | M17 implementation |
| [0006](./adr/0006-local-transcription.md) | Optional local transcription with whisper.cpp | M18 implementation |

Other architecture notes:

- [Profile calibration](./profile-calibration.md): upright normalized ROI canvas, keyboard controls, local overrides, safe patches, crop and SDK previews.
- [Banner and subtitle OCR](../detectors/text.md): local OCR, locale matching, line evidence, temporal intervals, optional data and validation limits.
- [Wanted-state detector](../detectors/wanted.md): calibrated analytic indicators, temporal confirmation, local replay/crops, synthetic validation and benchmark.
- [Local transcription](./transcription.md): optional whisper.cpp engine, explicit model installation and licenses, per-clip cached jobs, word timing in session time, storage, privacy notice and deletion, cancellation. User guide: [Local transcription](../guides/transcription.md).
- [Detector runtime](./detectors.md): trusted built-in SDK, immutable derived samples, profile inheritance/compatibility, provenance, caching, failure isolation and CLI.

- [Storage](./storage.md): what lives in SQLite vs on disk, delete policies, migrations, backups.
- [Worker lifecycle and jobs](./worker.md): process lifecycle, API, job handlers, cancellation, retry rules.
- [Media probing](./media.md): FFmpeg discovery and minimum version, `doctor`, the probe job, normalized metadata, error codes, fixtures.
- [Fingerprints and duplicates](./fingerprints.md): exact, fast, perceptual, and audio fingerprints, versioning, duplicate candidates, backfill.
- [Watched folders](./watched-folders.md): host watcher and stabilization, worker decisions, reconciliation, offline backoff, cloud placeholders, Xbox onboarding.
- [Overlap alignment](./overlap.md): finding repeated footage between adjacent clips (windows, sampling, thresholds, confidence), the shared timeline layout, overrides, performance, adversarial cases.
- [Virtual session timeline](./session-timeline.md): source ↔ virtual time mapping and its precision guarantees, the two-element session player, boundary and hidden-overlap behavior, keyboard controls, player limitations.
- [Sessions](./sessions.md): capture-time estimation (filename patterns, confidence), metadata grouping rules and the 15-minute default gap, idempotent recompute, and durable manual corrections.
- [Import from phone](./phone-upload.md): the separate LAN upload gateway, network model, 256-bit expiring token, limits and checks, filename rules, import handoff and staging cleanup. User guide: [Send clips from your phone](../guides/phone-upload.md).
- [Desktop library and jobs UI](./desktop-ui.md): routes and components, the allow-listed `worker_api` bridge, the `owm-media` playback protocol, job center behavior, keyboard access, tests, player limitations.
- [Derived media](./derived-media.md): proxy policy and preset, deterministic HDR tone mapping, filmstrip thumbnails, waveform format, cache keys and invalidation, artifact layout, cleanup, minimum FFmpeg capabilities.
- [Safe import pipeline](./import.md): reference and managed imports, staging and atomic promotion, idempotency, provenance, missing sources and relink, error codes.

- [Event review](./event-review.md): immutable snapshots, audited corrections, timeline markers and explicit reconciliation.
- [Local evaluation](../evaluation/README.md): holdout annotations, metrics, replay CLI and report privacy.

- [Story engine](./stories.md): deterministic narrative windows, speech boundaries, score components, candidate decisions and project handoff.

- [Editor projects](./editor-projects.md): non-destructive commands, undo, autosave recovery, migration and portable source relinking.
