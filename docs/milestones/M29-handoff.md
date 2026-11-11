## Milestone handoff

- Milestone: M29 — Windows packaging and model manager
- Outcome: Implementation candidate; **M29 is not complete** until the clean Windows
  11 x64 lifecycle qualification below is recorded. The GPL packaging exception
  was accepted by merging [PR #35](https://github.com/heetdalsania/openworld-moments/pull/35).
  This branch implements that plan; it does not begin M30 or publish an alpha.
- Files and modules changed:
  - `scripts/windows`, the explicit Tauri packaging overlay and Windows CI:
    verified source extraction, source-built GPL FFmpeg/libx264, frozen worker,
    native architecture/hash/license inventory, repeated-build comparison, NSIS
    lifecycle smoke and candidate checksums/notices/source artifacts.
  - Rust host/supervisor: release resource discovery and hidden-console worker
    startup; exact doctor/model-management API allowlist.
  - Worker runtime/resources/system doctor, model catalog/download manager, M18
    registry, durable job handler and authenticated API; safe optional uninstall.
  - Settings model manager, system/first-run panels, jobs invalidation and tests.
  - Contracts 1.23 schemas/generated bindings/fixtures, migration 0019, README,
    ledger, accepted ADR and packaging/transcription architecture notes.
  - Small prerequisite repair: the calibration Rust E2E helper now respects the
    existing `OWM_WORKER_PYTHON` override, as the other E2E helpers already do.
    This permits a fresh locked local environment without a skipped test or
    application import-path workaround.
  - Small prerequisite repair: watched-folder scans and native-event root aliases
    now use one stabilization/report key. Repeated macOS full-gate failures showed
    duplicate reports for the same unchanged file; a deterministic root-alias
    regression protects the fix without following source-file symlinks.
  - Small prerequisite repair: readiness is logged before publishing the worker
    handshake, and unexpected-exit diagnostics wait for the bounded stderr drain
    before snapshotting failure state. The original nine supervisor assertions,
    including immediate crash/restart and secret redaction, remain intact.
  - Small prerequisite repair: the UI subscribes before reading initial worker
    status and prevents a late startup snapshot from overwriting a live ready
    event. A controlled regression reproduces Import becoming disabled with the
    old code; this ordering must remain stable for packaged first-run checks.
  - Small prerequisite repair: production CSP blocked Ajv's runtime compiler,
    leaving the installed WebView blank. Contract generation now emits static
    validators; `load()` keeps schema/version/semantic checks without runtime
    string evaluation. The CSP remains unchanged. A Node subprocess regression
    validates all fixtures with string code generation disabled.
- Public contracts or migrations:
  - Contracts 1.23: `system-doctor`, `model-manager`, `model_download` job kind and
    mirrored Python/TypeScript semantic validation. Existing job routes own
    cancellation/retry; exact management routes are documented in the guide.
  - Migration 0019 rebuilds the jobs constraint while preserving existing rows,
    indexes and idempotency. Existing pre-migration backup/newer-schema refusal
    remains authoritative.
- Commands run:
  - Locked environment sync, formatting/generation, required-tool `pnpm check`
    using the fresh environment for uv and all native worker E2E subprocesses.
  - Worker mypy on Windows/Linux targets; Windows scripts compile and shell
    syntax checks; focused download/catalog/doctor/archive/uninstall regressions.
  - Real-worker synthetic browser fixture, Vite and Playwright Settings walkthrough.
  - Native macOS production build; hosted Windows commands/results recorded below
    when available. A macOS build is not Windows installer evidence.
- Test and validation results:
  - Required-tool full `pnpm check` passes: format, lint, REUSE, type checks, tests
    and generated-contract drift. Worker **1,121 passed, 1 skipped** (existing
    Windows-junction-only test on macOS); Python contracts **340**, TypeScript
    contracts **371**, desktop **252**, Rust **52** passed.
  - Worker mypy passes for both Windows and Linux targets (**208 files**).
    Build-script Ruff/import checks, Python compilation and shell syntax pass.
    After Windows CI exposed fixture handle retention and metadata encoding,
    SQLite test handles close explicitly and Cargo JSON is decoded as UTF-8.
    Nine focused uninstall/archive/artifact regressions pass, including repeated
    assembly with accurate checksums and exclusion of stale generated media.
    Standard-library ZIP order/metadata is normalized without changing module
    bytes, and the repeated-build gate still compares every payload hash.
    The existing phone countdown test flushes async mount effects before advancing
    fake time; its assertions and application behavior remain unchanged.
  - Model tests cover signed-catalog tampering, rejected origins, exact HTTP range
    resume, cancellation, ignored ranges, corruption/oversize, low disk/offline,
    Unicode paths, linked partials, active-job safety, removal and pinning.
  - Browser Settings walkthrough passed against the real local worker: core
    doctor checks, offline initial catalog, keyboard focus to Install, and no
    horizontal overflow at 800 px. No model download started. Native transport
    was bridged for this macOS browser fixture; it is not Windows evidence.
  - Export goldens were regenerated only for contract 1.23 and the derived privacy
    token. Corrupt-model transcription now fails at registry lookup and is tested
    as missing; the engine never starts.
  - Native macOS production `pnpm build` passes (existing chunk-size warning).
    Actual pinned FFmpeg/x264 sources pass the safe-extraction checks.
  - Hosted CI passed the NSIS build and complete frozen-payload reproducibility
    comparison. Native lifecycle testing remains pending. Elevated runner hosts
    need a temporary app-specific HKLM WebView2 debug policy because current
    WebView2 ignores environment/HKCU flags there. The harness removes the
    override in `finally`; the installer contains no debugging configuration.
    The harness waits for the native WebView target after connecting to CDP,
    since the browser endpoint can become ready before the window's page.
    The uninstall harness keeps its sentinel inside the actual library and checks
    the database SHA-256 before/after removal of application files, exporting a
    separate retention report. No clean Windows 11 client run is claimed.
- Decisions made:
  - Per-user NSIS `0.1.0-alpha.29`, stable application/library identity, x64 only;
    OS-managed WebView2. Required worker/FFmpeg tools are bundled and ignore
    development overrides. Optional OCR/whisper.cpp engines are not bundled.
  - Python 3.12.14 standalone 20260929, uv 0.13.7, PyInstaller 6.22.3, FFmpeg 9.0.2
    and pinned x264 source with SHA-256; dependency lockfiles and build inventory.
  - Offline bundled Ed25519 catalog, curated MIT tiny.en/base.en at immutable
    upstream revision. The initial signing key was generated in memory and
    discarded; changing the catalog requires a reviewed app/trust-root update.
    No keys, models or footage are committed. No automatic catalog refresh.
  - Downloads are explicit authenticated jobs, limited HTTPS origins/redirects,
    strict size/range/digest checks, partial resume, disk reserve and atomic
    promotion. Listings rehash contents. Cancellation never activates partial
    bytes; already committed verified versions may remain at the commit boundary.
  - Repair/upgrade/default and silent uninstall retain libraries. Interactive
    removal needs two choices, resolves a fixed OS Known Folder, refuses linked
    roots, and unlinks nested junctions rather than visiting external originals.
    NSIS recursive app-data deletion is disabled; preferences remain.
- Known limitations:
  - The host for local validation is macOS. Windows Server CI automation is
    intentionally separate from clean supported Windows 11 client qualification.
  - Unsigned candidate; SmartScreen/enterprise policy may warn or block. No paid
    signing procurement, release publication, or macOS/Linux installer is included.
  - Repeated frozen-payload hashes can be compared within a CI toolchain snapshot;
    cross-runner/compiler NSIS bit reproducibility is not claimed. MSYS2 compiler
    and installed package versions accompany the artifacts.
  - Real speech recognition/gameplay detector quality is unmeasured. Model tests
    use synthetic bytes and controlled HTTP interruption, never real weights.
  - Optional hardware encoders absent from the minimal source build are reported
    unavailable; the tested CPU encoder is the required fallback.
  - Windows 11 client run ([report](./M29-windows-client-report.md)) did not fully
    pass: in the M10 phone test a ~2 MB iPhone video was refused with "The computer
    is out of space." while ~181 GB was free. Repair and upgrade (steps 6.2 and 6.3)
    ran inside the Claude app's virtualized container and are recorded as passed by
    maintainer decision. Smaller defects: the cancelled-download job says "Nothing
    partial was kept" although the partial is kept; Cancel in Settings left the job
    "Working"; the desktop phone screen keeps the QR code at "Closes in 0:00" after
    the phone finishes.
- Follow-up milestones affected: M30, M31, M33 and M34 must respect the actual M29
  completion dependency. M32 remains the public alpha gate.
- Screenshots, reports, or artifacts: Ignored local Settings screenshot under
  `output/playwright`; CI candidate contains installer, runtime/source inventory,
  notices, checksums, build inputs and native lifecycle reports only. Synthetic
  media, model weights, scratch libraries, databases and build outputs are excluded
  from commits and candidate uploads.

Implementation pull request: [#36](https://github.com/heetdalsania/openworld-moments/pull/36) (draft; qualification pending).

### Dependency evidence

All dependency merge commits are ancestors of the implementation base `5ca9d27`:

| Milestone | Merged PR | Merge commit | Handoff inspected |
|---|---|---|---|
| M03 | [#7](https://github.com/heetdalsania/openworld-moments/pull/7) | `c3f983c` | PR handoff, worker architecture and ADR-0004 |
| M08 | [#13](https://github.com/heetdalsania/openworld-moments/pull/13) | `d89bf80` | PR handoff and derived-media architecture |
| M18 | [#24](https://github.com/heetdalsania/openworld-moments/pull/24) | `200aaed` | `M18-handoff.md` and model registry/adapter |
| M24 | [#30](https://github.com/heetdalsania/openworld-moments/pull/30) | `7a4233c` | `M24-handoff.md` and CPU encoder registry |

### Remaining qualification gate

Execute the [Windows client runbook](./M29-windows-client-runbook.md), which also covers
the pending M10 real-phone smoke test. It follows the clean Windows 11 x64 matrix in the
[packaging guide](../architecture/windows-packaging.md):
normal-user GUI install/launch without developer tools, first-run doctor, lawful
synthetic import/render, optional download interruption/failure/Unicode cases,
repair/upgrade with retained database/projects/backups, uninstall/reinstall
retention and separately confirmed disposable-library removal. Record OS/WebView
versions, artifact SHA-256, results and unsigned prompts. Hosted Server CI passing
alone does not close this gate. Keep the PR draft and M29 ledger In progress until
that evidence is available.
