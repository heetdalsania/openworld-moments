## Milestone handoff

- Milestone: M15 — Profile calibration UI
- Outcome: Settings opens a visual calibration screen for installed profiles and
  imported playback frames. Named normalized rectangles support pointer drawing,
  movement/resizing, precise keyboard controls and numeric edits. Local overrides
  persist independently, affect M14 analysis, and can be compared, reset, imported
  and exported without embedding media. Crop/preprocessing and the real synthetic
  SDK preview are available through separate explicit actions.
- Files and modules changed:
  - Desktop `CalibrationView.tsx`, `RoiCanvas.tsx`, `calibration.ts`; route/settings
    link, typed API client, authoritative query-cache updates and scoped styles.
  - Native host profile route allowlist, patch/sample save commands,
    `calibration.rs` exclusive-create output helper, `calibration_e2e.rs`.
  - Worker `detectors/calibration.py`, analyzer profile resolution, authenticated
    calibration/preview routes and request bounds.
  - Shared profile-patch schema, version policy, generated TS/Pydantic outputs,
    mirrored schemas, semantic checks and shared fixtures.
  - Component, coordinate, worker and native tests; architecture/authoring guides,
    contract changelog, README status/next steps and milestone ledger.
- Public contracts or migrations:
  - Contracts **1.10** add `ProfilePatch`: base identity/version/key, game family,
    frame compatibility, sparse regions and tool/UTC provenance. Unknown fields
    and out-of-bounds regions fail validation in both runtimes.
  - No migration; sparse overrides use existing `settings` keys
    `calibration.roi.v1.<profile-id>`.
  - `GET /v1/profiles`, `GET|PUT /v1/profiles/{id}/calibration`,
    `POST /v1/profiles/{id}/patch|reset|preview`; authenticated and allow-listed.
  - `calibration_export_patch(profile_id)` reads validated saved state from the
    worker. `calibration_export_sample(data)` is a separate bounded PNG export.
    Native save dialogs return saved/cancelled; output requires a new filename.
- Commands run:
  - `OWM_REQUIRE_FFMPEG=1 pnpm check`.
  - `pnpm build` (production desktop, no installer).
  - Focused UI/coordinate, calibration worker and Rust integration/export tests.
  - `pnpm contracts:generate` and deterministic `contracts:check`.
  - Worker `mypy --platform win32`, `--platform linux` and the normal darwin lane.
  - Playwright CLI real-Chromium walkthrough with a temporary host bridge and
    isolated FFmpeg-generated source clips/proxies; no user library used.
- Test and validation results:
  - Full local quality gate passes: formatting, ESLint/Clippy/Ruff, REUSE,
    TS/mypy, all tests and generated-contract drift. Production build passes on
    local macOS arm64 (no installer); Vite reports a non-blocking >500 kB chunk.
  - Worker: **571 passed, 1 skipped** (the existing Windows-only junction test
    on macOS). No M15-required validation was skipped.
  - Python contracts: **153 passed**; TypeScript contracts: **162 passed**;
    desktop: **130 passed**; Rust: **47 passed** on this Unix host.
  - Worker mypy passes for darwin, win32 and linux. Additional focused checks
    cover the final reused-player and native production-export helper paths.
  - Coordinate tests round-trip 720p/1080p/4K and cover 4:3, portrait, ultrawide,
    letterbox transforms, edges, exact source-pixel increments and preprocessing.
  - UI tests cover loading/empty/error/retry, invalid saves, custom names,
    keyboard move/resize at five frame shapes, export cancellation, patch
    import/reset, stale-profile reload, navigation persistence, preparation,
    decode failure and reused-player readiness.
  - Worker tests cover sparse patch export/import/reset, database reopen,
    immutable installed files, effective analyzer keys, profile update/default
    inheritance, compatibility conflicts/stale keys, media/identity/version
    rejection, count/size boundaries and ephemeral SDK success/negative cases.
  - Native E2E uses the real supervised worker and allow-listed routes, writes
    exported JSON then imports it, restarts, rejects invalid regions and resets
    exactly to base. Output helper tests preserve existing files and source
    hardlinks/symlinks.
  - Real Chromium exercised capture and SDK preview on generated 720p, 1080p,
    4K, 4:3 and portrait sources, keyboard controls, pointer drawing, Escape
    cancellation, preprocessing and save/export/import/reset. The export bridge
    substitutes for the native picker; native dialog interaction is not claimed.
- Decisions made:
  - Upright picture coordinates exclude letterbox bars. Keyboard steps use source
    dimensions; crop pixels come from the actual SDR playback copy.
  - Sparse overrides survive base changes while untouched defaults follow the
    new profile. Family/frame conflicts fail closed and retain the saved patch.
  - Save/preview check the base digest; explicit reload discards the UI draft.
    Reset restores the exact current base values and original analyzer key.
  - Base region names stay fixed because detectors/safe zones reference them;
    new named regions can be added or removed. No upstream profile edits occur.
  - Preprocessing is an inspection tool. The real SDK preview uses one 64×36
    grayscale frame, preserves confirmation rules and never saves observations.
  - Existing files are never replaced by export; callers choose a new JSON/PNG
    filename. Patch and crop exports remain distinct.
- Known limitations:
  - Synthetic bright-region detector only; no gameplay accuracy, models/OCR,
    training, marketplace or temporal replay UI. One sample normally produces
    no confirmed event under the default three-frame rule.
  - Rectangles only. Browser-decoded proxy seeking is not a guarantee of exact
    source-frame selection. Capture requires a ready playback copy.
  - Crop preprocessing does not alter installed detector algorithms. Calibrating
    a different-shaped frame does not establish profile/game compatibility.
  - Native save-picker interaction, WKWebView/WebView2 runtime and physical
    Windows/macOS release qualification remain distinct from Chromium evidence.
  - The upstream M08 validator rejected an exploratory 2-second 4-fps fixture's
    end sample; browser qualification used generated 30-fps fixtures. No M08
    behavior was changed in this milestone.
  - Existing M10 real-phone Windows smoke test remains pending.
- Follow-up milestones affected:
  - M16 and M17 become Ready on merge. They can use persisted normalized ROIs
    and add explicit preview adapters for their detectors.
  - M18 and M21 remain independently Ready. M19 owns event review/reconciliation;
    M29 bundles the source catalog; M30/M31 and platform milestones harden delivery.
- Screenshots, reports, or artifacts:
  - Desktop and narrow-layout calibration screenshots shared in the task as
    `m15-calibration.png` and `m15-calibration-narrow.png`.
  - Coordinate behavior, patch format, accessibility controls and canvas limits
    documented in `docs/architecture/profile-calibration.md`.
  - No generated footage, crops, screenshots, libraries/databases, models,
    secrets, private paths or build outputs are included in this commit.
