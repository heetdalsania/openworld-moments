## Milestone handoff

- Milestone: M19 — Event review and evaluation
- Outcome: Sessions expose timeline markers and readable detector/profile/tool
  provenance, original evidence and an audited effective view. Users explicitly
  approve, reject, relabel, change intervals, reset or create manual events.
  Local evaluation produces deterministic privacy-minimized JSON/Markdown metrics
  and compatibility rows from a hash-addressed holdout and frozen observations.
- Files and modules changed:
  - Worker `review/service.py`, migration `0012_event_review.sql`, API routes,
    analyzer snapshot writes and session attached-data guards.
  - Worker `evaluation/`: matching, metrics, bounded input loading, explicit local
    capture, independent synthetic holdout generation and `owm eval` CLI.
  - Desktop `EventReviewPanel`, session integration, API client, job invalidation,
    styles and Rust host allowlist.
  - Four contract schemas, generated TypeScript/Pydantic, dual-runtime semantics,
    valid/invalid fixtures and versioning documentation.
  - Review, metrics, media/API, migration, desktop and host tests; architecture,
    evaluation, fixture, README and milestone documentation.
- Public contracts or migrations:
  - Contracts **1.14** add `event-review`, `evaluation`,
    `evaluation-observations` and `evaluation-report`. Prior 1.x documents remain
    readable. Inputs are closed, bounded and semantically checked in TS/Python.
  - Migration **0012** adds immutable original snapshots and append-only decisions;
    it does not change or rewrite existing producer event records.
  - `GET /v1/sessions/{id}/review`, `POST /v1/sessions/{id}/review`, and
    `POST /v1/sessions/{id}/review/{eventId}`. Mutations require layout identity;
    reviews also require the expected revision. Existing analyze jobs are now
    allowlisted for the desktop.
  - `owm eval holdout`, `owm eval capture`, `owm eval run`. Public manifests use
    SHA-256; a separate private local-file map never enters a report.
- Commands run:
  - M18 baseline: `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - `pnpm contracts:generate`, `pnpm format`.
  - M19: `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - Worker `mypy --platform win32` and `mypy --platform linux`.
  - `pnpm build` (production macOS arm64 desktop, no installer).
  - Focused review/evaluation/media pytest and desktop Vitest runs.
  - `owm eval holdout`, `capture`, `run`; two frozen report runs compared bytewise.
  - Playwright CLI Chromium event-review flow against an isolated real worker via
    a test IPC/media bridge, using generated media only.
- Test and validation results:
  - **M18 verified** against merged PR [#24](https://github.com/heetdalsania/openworld-moments/pull/24),
    main `200aaed456aaa09e25768e37ac96e89f10f55ee3`; hosted run 42408785984 passed.
    M13/M16/M17/M18 dependencies are merged. Baseline: worker **867 passed,
    1 skipped**, Python contracts **194**, TS contracts **206**, desktop **138**,
    Rust **47**. M18 whisper.cpp arguments/offset handling were checked against
    the upstream CLI source. No blocking issue found; no M18 product code changed.
  - **M19 local gate:** formatting, ESLint/Clippy/Ruff, REUSE, TypeScript, mypy,
    tests and generated-contract drift check pass. Worker **879 passed, 1 skipped**;
    Python contracts **210**, TS contracts **226**, desktop **147**, Rust **47**.
    The skip is the existing Windows-only junction case on macOS.
  - Review coverage checks immutable originals, every decision action, manual
    intervals, auth/foreign IDs, bounds, stale layouts, optimistic revision races,
    legacy refusal, paginated/truncated history, failed/cancelled/successful
    reanalysis and retained archived data after an empty result.
  - Metrics cover inclusive tolerance boundaries, both timestamp boundaries,
    maximum-cardinality matching, duplicates/types, empty/negative datasets,
    undefined ratios, FP/hour denominator, timing and processing cost. Real
    FFmpeg capture checks media hashes/metadata, cancellation, malformed inputs,
    manifest binding, deterministic bytes and report privacy.
  - Desktop coverage checks readable evidence/spoilers, actions/manual insertion,
    historical states, conflicts, explicit profile choice, cancelled analysis,
    errors, unique/revealed time mapping and cached-layout/hash-unavailable refusal.
  - Synthetic holdout: **19 seconds**, **3 TP / 0 FP / 0 FN**, precision/recall/F1
    **1.0**, timestamp error **0 ms**, **6.16× real time** on Apple M4 including
    proxy preparation/decode but excluding import/source hashing. These results
    qualify this small synthetic example only.
  - Production macOS arm64 build passes; no Windows executable/device or native
    Tauri WebView interaction is qualified by the Chromium bridge.
- Decisions made:
  - Keep original observations separate from audited corrections. Reset appends a
    decision; it never deletes history or changes confidence/evidence/provenance.
  - Reanalysis keeps reviewed replaced IDs as read-only `superseded` history.
    New IDs need separate review; no similarity matching transfers approval.
    Manual events survive reruns; changed layouts make prior events stale.
  - The desktop independently hashes the displayed layout before enabling seeks
    or edits. The server rechecks layout and revision inside the write transaction.
  - Match same-type intervals only when both boundaries meet inclusive tolerance.
    Deterministic augmenting paths maximize TP count; they do not globally minimize
    timing error among equally sized assignments.
  - Freeze measured observations as well as annotations for byte-reproducible
    reports. A fresh capture can have different processing times.
  - Synthetic compatibility stays `synthetic-only`; other rows stay `unvalidated`.
    Prominent UI warnings never imply GTA VI support.
- Known limitations:
  - No gameplay quality qualification or calibrated confidence. Wanted, OCR and
    audio producers need independent annotated holdouts; this milestone does not
    train or retune them. GTA VI remains Unvalidated with zero measured gameplay.
  - M18 still has no real whisper.cpp engine/model quality or performance run;
    transcription tests use a test double. Its documented snapshot policy remains.
  - Archived originals/decisions remain until session/library deletion; the UI
    pages 50 events and shows the latest 20 decisions per event.
  - Legacy `GET /v1/events` still returns raw producer observations. Consumers
    needing user decisions must use the current effective review projection.
  - Chromium validation uses a test IPC/media bridge, not the native Tauri host;
    Rust allowlist tests and the production build provide separate host evidence.
  - Existing M10 real-phone Windows smoke test remains pending.
- Follow-up milestones affected:
  - **M20** can begin after M19 merges. It must use current effective decisions,
    exclude stale/superseded observations, define rejected/unreviewed policy, and
    preserve supporting-only audio semantics.
  - **M21** remains independently ready. M26 can consume review views for search.
  - M29/M32/M34 retain platform/package/real-engine qualification work.
- Screenshots, reports, or artifacts:
  - [Sample report](../evaluation/sample/report.md), [JSON](../evaluation/sample/report.json),
    [frozen observations](../evaluation/sample/observations.json), and
    [holdout manifest](../../fixtures/manifests/evaluation-holdout-v1.json).
  - [Annotation and CLI guide](../evaluation/README.md),
    [review architecture and reconciliation](../architecture/event-review.md).
  - Chromium screenshots/logs are local validation artifacts outside Git. No
    footage, models, private maps/paths, libraries, databases, secrets or build
    outputs are committed.
