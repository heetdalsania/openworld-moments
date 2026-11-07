## Milestone handoff

- Milestone: M14 — Detector SDK and profile schema
- Outcome: A local, built-in detector runtime analyzes immutable samples from M08
  derived proxies, validates evidence-backed events, isolates producer failures,
  supports cancellation/resume, and caches successful results independently.
  Local JSON profiles support bounded inheritance, licenses, capability/locale
  metadata and compatibility checks. The synthetic temporal example runs from CLI.
- Files and modules changed:
  - Worker `detectors/{sdk,profiles,inputs,example,service,__main__}.py`.
  - Analyze job registration, authenticated API routes, event provenance storage.
  - Migration 0010 and its upgrade fixture.
  - Shared contracts, generated TypeScript/Pydantic outputs and cross-runtime fixtures.
  - `profiles/generic-open-world/profile.json`; runtime/authoring/storage/API docs,
    README status/commands/next steps, and milestone ledger.
- Public contracts or migrations:
  - Contracts **1.9**, additive: profile inheritance/license/capability/locale fields,
    detector event `tool_versions` and `input_key`, and `AnalysisResult` outcomes.
  - Migration **0010** adds event provenance columns and `detector_runs` cache rows.
  - `POST /v1/sessions/{id}/analyze` returns an `analyze` job. Optional idempotency,
    selected locale and forced recomputation use the existing job engine.
  - `GET /v1/events?session_id=&limit=&offset=` returns bounded event snapshots.
  - `owm profiles validate <manifest.json>`, `owm analyze <session> --library <dir>
    --profile <id>`, `owm demo` (or `python -m openworld_moments.detectors`).
- Commands run:
  - `OWM_REQUIRE_FFMPEG=1 pnpm check`.
  - `pnpm build` (production, no installer).
  - `pnpm contracts:generate` repeatedly; final `contracts:check` confirms no drift.
  - Worker `mypy --platform win32`, `--platform linux`, `--platform darwin`.
  - Focused detector/media/migration tests; profile validation CLI; `owm demo`.
  - Five-run in-memory synthetic processing measurement.
- Test and validation results:
  - Full local quality gate passes: format, ESLint/Clippy/Ruff, REUSE, type checks,
    tests and contract drift. Production desktop build passes on macOS arm64.
  - Worker: **553 passed, 1 skipped**. The skip is the existing Windows-only
    junction cleanup case on macOS; no M14-required test is skipped.
  - Python contracts: **147 passed**. TypeScript contracts: **155 passed**.
  - Desktop: **106 passed**. Rust: **44 passed** (unit and integration suites).
  - M14 runtime tests cover hostile/invalid profiles, inheritance and cycles,
    field paths, compatibility, frozen input maps/frames, evidence/version/range
    rejection, setup/factory/detect/close failures, partial-failure job status,
    cancellation/resume, cached IDs, producer/profile/input/tool/locale/layout
    invalidation, reviewed-event retention and concurrent layout changes.
  - Real FFmpeg tests cover the generated example, validated proxy input, source
    hash/mtime preservation, refusal of changed proxy bytes, decode cancellation,
    authenticated job/API execution and CLI success/failure.
  - Synthetic-only processing loop: 7,200 64×36 white frames (one hour at 2 fps)
    in median **0.099 s**, range 0.097–0.130 s over five runs on local arm64;
    excludes generation, decode and I/O. Not gameplay-detector performance proof.
- Decisions made:
  - Fixed source registry of trusted built-ins; no executable plugin loading.
  - Apache-2.0 SDK types, AGPL execution engine; profile/schema data stays Apache.
  - JSON profiles and local IDs only, no network/YAML loader or dependency added.
  - Derived-only 64×36 grayscale sampling at 2 fps with bounded output/timeouts.
  - One successful result transaction per clip/detector. Failed replacements keep
    earlier results; cancellation keeps completed units for resume.
  - Re-analysis replaces only its producer's unreviewed records. Reviewed/user
    observations stay intact. M19 owns correction/re-analysis reconciliation.
  - Event times use M13 unique session time; source intervals remain in attributes
    and evidence. Layout changes require explicit re-analysis.
- Known limitations:
  - Synthetic bright-region example only; no GTA detection or measured game
    compatibility, models, OCR, transcription, calibration or review UI.
  - The SDK is a capability boundary for cooperating built-ins, not an OS sandbox
    for arbitrary Python. Cooperative detector code must remain bounded.
  - Sampling is coarse; no source-frame accuracy claim. Raw decode is capped at
    64 MiB per asset and 600 seconds; only one asset's sample set is retained.
  - Catalog discovery defaults to the source repository; packaged catalog/runtime
    bundling remains M29. CLI accepts an explicit catalog path.
  - Hosted Windows/Linux CI is separate from the local checks described here.
  - Existing M10 real-phone Windows smoke-test requirement remains pending.
- Follow-up milestones affected:
  - M15 (profile calibration) and M18 (audio/transcription) become Ready on merge.
  - M16/M17 can add versioned built-ins after M15; M19 adds review/evaluation.
  - M21 remains independently Ready after M13.
  - M29 must bundle/discover profiles, worker and media tools; M30 audits delivery.
- Screenshots, reports, or artifacts:
  - Runtime and authoring guides in `docs/architecture/detectors.md` and
    `docs/detectors/README.md`; shared synthetic fixtures and executable tests.
  - No visual UI changes. No generated footage, models, databases, binaries,
    build outputs or private library data are included in the commit.
