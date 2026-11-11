## Milestone handoff

- Milestone: M31 — Accessibility, onboarding, and documentation
- Outcome: **Implemented; not yet complete.** The Windows manual checks (a clean
  standard-account pass through every guide, and Narrator/NVDA smoke tests) are
  outstanding; the [Windows runbook](./M31-windows-accessibility-runbook.md) lists them.
  Everything else is done and checked automatically or in a real browser engine.
  - **First-run setup:** six skippable steps (spec 10.2):
    - welcome: states the app never connects to, runs on or changes a console, game or
      account, and reads no game memory or network traffic;
    - system check;
    - import methods and the default import mode;
    - privacy choices;
    - display;
    - done.

    Choices save as they are made; **Run setup again** is in Settings.
  - **Informed opt-in:** phone transfer (LAN) and optional model downloads are off by
    default. Each is explained before it can be turned on, and both are enforced in the
    UI and at the single entry points (`startPhone`, `installModel`).
  - **Accessibility:**
    - keyboard-complete import → review → edit → render → **Show in folder**;
    - an import dialog that traps Tab and returns focus;
    - live-region announcements for job completion and failure;
    - Light, Dark and High-contrast themes, plus `prefers-contrast` and Windows forced
      colors;
    - text size 100–200% and reduced motion;
    - status in words, never color alone;
    - a wrapping top bar, so 200% text or zoom and narrow windows don't scroll sideways.
  - **Diagnostics export:** a previewed, redacted support report (contract 1.24) with
    versions, system check, counts and error codes. No footage, file names, paths or
    tokens; error messages only on opt-in, still redacted. The host saves it; nothing
    is uploaded.
  - **Locating output:** **Show in folder** for finished renders and **Show library
    folder** in Settings; the host checks the file is inside the library and opens
    the file manager without a shell.
  - **User guides** (`docs/guides`), each versioned, dated and link-checked:
    - getting started, Xbox through OneDrive, PlayStation and phone clips, watched
      folders, capture cards;
    - troubleshooting, diagnostics, known limitations;
    - terminology, accessibility (shortcuts and support matrix), compatibility notes;
    - nine screenshots from the real UI with synthetic data.
- Files and modules changed:
  - **Worker:** `diagnostics.py` (report, message scrubbing, read-only counts) and
    `api/app.py` (`POST /v1/diagnostics`).
  - **Contracts:** `diagnostics-report.schema.json`, a semantic rule in Python and
    TypeScript, fixtures, and the version bump to 1.24 (CHANGELOG, VERSIONING).
  - **Host (Rust):**
    - `reveal.rs` (library-confined render paths, file manager without a shell);
    - `host.rs` (`diagnostics_export`, `render_reveal`, `library_reveal`);
    - `media.rs` (`POST /v1/diagnostics` route);
    - `lib.rs` (registration).
  - **Desktop:**
    - new: `Onboarding`, `PrivacyChoices`, `AppearanceSettings`, `DiagnosticsPanel`,
      `Announcer`, `preferences.ts` and `a11y.ts`;
    - changed: `App` (setup gate, Settings sections, Help and setup), `SystemPanel`
      (plain check with status words), `PhoneImport` and `ModelManager` (consent
      gates), `ExportPanel` (Show in folder), `ImportPanel` (dialog focus), `jobs.ts`
      (`watchJobs`), `phone.ts` and `api.ts`, `styles.css` (themes, forced colors,
      motion, wrapping top bar, focus for date fields).
  - **Tests:**
    - desktop: `accessibility.test.tsx` (axe-core, token contrast),
      `Onboarding.test.tsx` (setup, consent, preferences, announcements, diagnostics,
      dialog focus), `testing/setup.ts`, ExportPanel keyboard and reveal tests,
      updated SystemPanel tests;
    - worker: `tests/test_diagnostics.py` and `tests/test_user_guides.py`;
    - Rust: reveal and route tests.
  - **Scripts:** `scripts/docs/` (`harness.py`, `fake-host.js`,
    `capture-screenshots.py`, `a11y-smoke.py`); `scripts/windows/native-smoke.py`
    walks the new setup.
  - **Docs:**
    - `docs/guides/*` (11 new or rewritten guides, plus the existing three updated);
    - the desktop UI, worker, architecture index and Windows packaging docs;
    - the threat model (P1, U4, X4);
    - the M31 runbook, README and ledger.
  - **Dependencies:** `axe-core` (MPL-2.0) as a desktop dev dependency only.
- Public contracts or migrations:
  - **Contracts 1.24:** the new `diagnostics-report` contract. Its `privacy` block is
    fixed by the schema, and a semantic rule rejects failure messages unless the user
    opted in. Existing 1.x documents stay readable. No migration.
  - **Worker API:** `POST /v1/diagnostics`.
  - **Host commands:** `diagnostics_export`, `render_reveal`, `library_reveal`.
  - **Preferences:** stored under the local-storage key `owm.preferences.v1`.
  - **Behavior change:** after updating, phone transfer and model downloads are off
    until the user turns them on (documented in Compatibility notes).
- Commands run:
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`, worker
    `mypy --platform darwin|win32|linux`, `pnpm build`, `cargo clippy -D warnings`.
  - `scripts/docs/a11y-smoke.py` and `scripts/docs/capture-screenshots.py` (Chrome via
    Playwright, synthetic data).
- Test and validation results:
  - **Gate:** `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check` passes.
    - Worker: 1,215 passed, 1 skipped (the existing environment skip).
    - Contracts: 345 Python and 377 TypeScript tests.
    - Desktop: 281 tests.
    - Rust: 58 tests.
    - Lint, formatting, REUSE and contract drift are clean.
  - **Worker mypy** for darwin, win32 and linux: clean. **`pnpm build`:** passes.
  - **Goldens:** the export goldens were regenerated for the 1.24 version string. The
    review token is derived from the versioned document, so it changed with it.
  - **Flaky test (not M31):** under full-gate load, the existing Rust watch test
    `slowly_written_file_is_reported_once_after_it_stops_changing` failed once on its
    timing assertion. It passed in the other gate runs and five isolated reruns, and
    M31 does not touch the watcher.
  - **axe-core:** no violations on Library, Settings, Search, Projects, Phone (allowed
    and not allowed) and all six setup steps. It found one issue during development
    (duplicate region names in setup), now fixed.
  - **Contrast:** every theme's text, muted text, links, primary buttons, warnings and
    focus ring meet WCAG AA, and High contrast meets AAA. The check found the default
    light warning color at 4.36:1; it is now 5.56:1.
  - **Browser smoke** (`a11y-smoke.py`): 29 of 29 checks pass:
    - first Tab stop is Skip to content;
    - focus visible at every stop on four screens;
    - setup by Enter, Import dialog trap and Escape;
    - no horizontal scrolling at 200% text, 200% zoom and 400 px;
    - forced-colors focus, high-contrast theme, reduced motion.

    It found and fixed:
    - a top bar that did not wrap (up to 384 px of sideways scrolling);
    - date fields without a visible focus ring.
  - **Diagnostics:** realistic personal data (Windows, POSIX and UNC paths, file names
    with spaces, bearer tokens) never reaches the report, with or without messages; the
    report is contract-valid; the API previews exactly what it saves.
  - **Docs:** 30 checks: required topics, version lines, every link, anchor and image,
    the index, no orphan or oversized images, no PNG text metadata, no personal paths.
- Decisions made:
  - **Spec references:** the brief's sections 12, 16, 17.3 and 20 are performance,
    delivery, epics and risks. The UI work follows 10.2 (onboarding) and 10.8
    (application accessibility); risks 20 (PS5 ingestion, one-click expectations) are
    addressed by the setup and guides.
  - **Library location stays fixed in the alpha** (spec 10.2 step 1). Setup and
    Settings show where it is and open it. Making it movable needs host configuration
    and migration work outside M31's in-scope list.
  - **Preferences live in the webview's local storage.** Losing them is safe: the
    defaults are setup pending and both network features off.
  - **The diagnostics report is a fixed contract, not a log bundle.** Logs aren't
    persisted, and a fixed shape makes "nothing personal" testable.
  - **Screenshots come from the real UI with a stubbed host and synthetic data**,
    which is reproducible and never shows a real library.
- Known limitations:
  - **Not yet done (blocks Complete):**
    - a clean Windows 11 standard-account pass through every guide;
    - Narrator and NVDA smoke tests;
    - a keyboard pass in the packaged WebView2 app.

    See the [runbook](./M31-windows-accessibility-runbook.md).
  - **Usability pass:** a heuristic review by the implementer, not sessions with fresh
    users. It fixed:
    - mismatched import-mode wording between setup and the Import dialog;
    - a render location shown only as a library-relative path, now Show in folder;
    - upper-case status codes, now status words;
    - "1 recent failures".

    Sessions with real first-time users remain for M32.
  - **Exceptions** (accessibility guide): the browser-drawn focus ring on date-field
    calendar buttons; drawing new calibration regions is easiest with a mouse;
    timeline click-scrubbing has keyboard alternatives but is not itself keyboard
    operable.
  - **Still open from earlier milestones:** M40 (standard-user firewall prompt, #38
    retest). Transcription still needs a separately installed whisper.cpp.
- Follow-up milestones affected:
  - **M32:** run the M31 runbook as part of Windows public-alpha qualification, plus a
    fresh-user session.
  - **M38:** reuse the setup, preferences, themes, announcer, guides structure and
    smoke harness for macOS (VoiceOver).
  - **M40:** unchanged.
- Pull request: this PR
- Screenshots, reports, or artifacts:
  - `docs/guides/images/*.png`: nine screenshots, synthetic data only, no text metadata.
  - The [accessibility support matrix](../guides/accessibility.md#support-matrix).
  - No footage, libraries, models, databases, credentials or build outputs are included.
