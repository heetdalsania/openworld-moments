## Milestone handoff

- Milestone: M27 — Open exports and manifests
- Outcome: Saved projects export to documented open formats: versioned project JSON,
  session-event JSONL, SRT and WebVTT captions, CSV markers, OpenTimelineIO and
  experimental FCPXML.
  - Every completed render has a complete reproducibility manifest: source hashes,
    project revision, preset, encoder, FFmpeg and render-engine versions, output
    hash, and detector and profile versions.
  - Exports are deterministic. They are built only from saved data, so re-exporting
    unchanged data gives identical bytes.
  - Each declares its version, stability and capabilities, and lists warnings for
    anything it cannot represent instead of dropping it silently.
  - Absolute source paths appear only when the user ticks **Include file
    locations**, and only in project JSON, OTIO and FCPXML.
  - The editor's Export panel saves each format through the host's native save
    dialog.
- Files and modules changed:
  - **Worker:** `exports/formats.py` (pure serializers), `exports/service.py` (reads
    saved data, session-to-project event mapping, render manifest re-export); render
    completion writes the enriched manifest and stores it; export and manifest API
    routes; migration `0017_render_manifests.sql`, fixture `data_v0017.sql`;
    OpenTimelineIO 0.18 as a dev-only dependency with a mypy override.
  - **Contracts:** 1.21 `export-result`, `project-export`, `event-export`, extended
    `export-manifest`, generated TS/Pydantic, cross-field rules, fixtures; the
    closed-schema test accepts a record union whose branches are closed.
  - **Desktop:** `OpenExports.tsx`, a per-render **Save manifest…** action, API
    calls. The host adds `project_export` and `render_manifest_export` commands
    (fixed extensions, plain names, no overwrite) and two allowlisted routes.
  - **Docs:** [exports](../architecture/exports.md), render, storage, desktop UI,
    architecture index, contracts changelog/versioning, README and ledger.
  - **Tests:** `tests/exports/` (formats, goldens, API), `tests/media/test_caption_playback.py`,
    the render golden's manifest checks, `ExportPanel.test.tsx`, host and allowlist
    tests.
- Public contracts or migrations:
  - **Contracts 1.21**, additive:
    - `export-result`;
    - `project-export` (format `openworld-moments.project` 1.0);
    - `event-export` (format `openworld-moments.events` 1.0, JSONL header and record
      lines);
    - `export-manifest`: optional `render_id`, `project_revision`, `encoder`,
      `tools`, `output`, `profiles`.
  - **Migration 0017:** `render_jobs.manifest_json`.
  - **API:**
    - `POST /v1/projects/{id}/exports` `{format, include_paths?}` → `ExportResult`
    - `GET /v1/renders/{id}/manifest` → `ExportResult` (404 unknown, 409 not
      completed)
  - **Host commands:** `project_export`, `render_manifest_export`.
- Commands run:
  - `pnpm contracts:generate`, `pnpm format`.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - Worker `mypy --platform darwin|win32|linux`.
  - `pnpm build`.
  - `uv run otiostat tests/exports/goldens/timeline.otio`.
  - `OWM_UPDATE_GOLDENS=1 uv run pytest tests/exports` (deliberate golden creation).
- Test and validation results:
  - **Full gate** (`OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`): formatting,
    ESLint/Clippy/Ruff, REUSE, TypeScript and mypy, all tests, and the contract drift
    check pass.
    - Worker: **1051 passed, 1 skipped** (the existing Windows-only junction case on
      macOS).
    - Python contracts **321**, TypeScript contracts **348**, desktop **222**, Rust
      **50**.
    - Two M26 tests that hard-coded contract version 1.20 and "latest migration"
      were made version-independent.
  - **Other checks:** mypy passes for darwin, win32 and linux, and the production
    macOS arm64 build passes.
  - **Exports** (`tests/exports/`, 21):
    - byte-exact goldens for all seven formats, plus repeat-export identity;
    - unrelated sessions and unsaved recovery drafts change nothing; a saved change
      changes only the affected formats;
    - project JSON lossless against the saved document, with forward-compatible
      `extensions`;
    - every JSONL line validates; ordering, effective vs original values and project
      ranges (inside, outside, rejected kept);
    - SRT/WebVTT round trips and byte parity with the desktop serializer's shared
      fixtures (Unicode, escaping, multi-line);
    - CSV parses back, with a formula guard, sorted rows and CRLF;
    - OTIO read and rewritten by OpenTimelineIO 0.18 (clip ranges, duration,
      markers, metadata preserved);
    - FCPXML well-formed with spine timings, escaping and the experimental label;
    - privacy: no paths without opt-in, refused for caption/marker/event formats;
    - missing-source and unsupported-operation fixtures; caption style and invalid
      caption refusals;
    - routes and manifest 404/409/byte stability.
  - **Caption playback spot check:** FFprobe reads exported SRT and WebVTT with the
    project's exact cue times.
  - **Real render:** the manifest records hashes, revision, encoder, FFmpeg version
    and output hash; the sidecar, stored copy and API re-export are identical bytes.
  - **External OTIO validation:** `otiostat` parses the golden (2 tracks, 4 clips,
    tracks equal length, 43.3 s = 00:00:43:18 at 60 fps).
  - **Desktop:** format choice, opt-in paths only where supported, flush before
    export, warnings after save, cancelled save, manifest save and refused-export
    message. **Host:** fixed extensions and plain-name filenames.
- Decisions made:
  - **Export contracts are separate from database rows.** The project export wraps
    the M21 portable envelope (so it imports back), and event lines pair the original
    observation with the effective review view.
  - **Determinism:** no clock reads (stored `saved_at` and render finish time), sorted
    keys, fixed ordering, canonical JSON; manifests are stored at render time so
    later re-analysis cannot change them.
  - **OTIO timing** uses the first clip's frame rate (30 fps fallback) with exact
    millisecond values, after `otiostat` showed a millisecond timebase breaks
    timecode tools. FCPXML stays in milliseconds and is labelled experimental.
  - **Captions** use the same plain-text rules as M23, verified byte-for-byte against
    the desktop fixtures.
  - **Unsupported operations** become warnings, and their values are kept under
    `openworld_moments` metadata in OTIO.
  - **Rejected events** are excluded from markers but kept in JSONL.
  - **Saving through the host** (fixed extension, plain filename, exclusive create);
    the web view never supplies a path or the content.
- Known limitations:
  - **FCPXML:** experimental; millisecond times may not be frame-aligned; no Apple DTD
    validation offline; not tested in Final Cut Pro.
  - **OTIO:** not yet opened in a third-party editor (DaVinci Resolve, Premiere,
    Kdenlive); validated with the OpenTimelineIO library and `otiostat`.
  - **Single frame rate:** OTIO uses one rate (the first clip's) for the whole
    timeline.
  - **No EDL**, and no import of third-party projects (out of scope).
  - **Manifest scope:** detector/profile versions cover the project's session events
    at render time, not only those inside the cut.
  - **Spec reference:** the brief cites spec section 13.5, which the specification
    does not contain (it ends at 13.4); 8.9 and 19.4 were read.
  - **Still outstanding from earlier milestones:** M10's real-phone Windows smoke
    test, unvalidated GTA profiles and unmeasured real whisper.cpp recognition.
- Follow-up milestones affected:
  - **M28** (privacy review) should gate exports as well as renders; blur regions
    already raise an export warning.
  - **M29** packaging needs no new runtime dependency (OTIO is test-only).
  - **M31** documentation can link the format reference.
- Pull request: PR_LINK
- Screenshots, reports, or artifacts:
  - [Open exports and manifests](../architecture/exports.md) (format reference,
    versions, privacy, warnings, validation commands) and the goldens in
    `services/media-worker/tests/exports/goldens/`.
  - No secrets, user libraries, private paths, footage, generated media, models,
    databases or build outputs are included.
