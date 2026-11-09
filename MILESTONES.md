# OpenWorld Moments Milestones

This document is the execution index for the repository. Every implementation task is called a **milestone** and is designed to fit one focused agent or contributor session. The roadmap contains 40 milestones, M00 through M39. Each milestone should normally produce one branch, one pull request, and one mergeable increment.

The detailed product requirements remain in [OPENWORLD_MOMENTS_BUILD_SPEC.md](./OPENWORLD_MOMENTS_BUILD_SPEC.md). Individual briefs live in [docs/milestones](./docs/milestones/).

## Milestone contract

An agent assigned a milestone must:

1. Read the repository README, product specification, this index, and the assigned brief.
2. Confirm every dependency is already merged.
3. Work only within the milestone's scope.
4. Preserve existing user and contributor changes.
5. Add or update the tests required by the brief.
6. Run all milestone validation commands plus repository-wide checks affected by the change.
7. Update documentation and contracts when behavior changes.
8. Update the README's **Project status** table and **Current next step** section.
9. Finish with a handoff summary using the template in [CONTRIBUTING.md](./CONTRIBUTING.md).

A milestone is not complete when the code merely compiles. It is complete when every acceptance criterion is demonstrably satisfied.

## Branch and pull-request convention

```text
Branch: milestone/MXX-short-name
PR:     [MXX] Imperative description
Commit: MXX: concise change description
```

Do not combine milestones in a single branch. If a blocking prerequisite defect is discovered, either stop and report it or make the smallest prerequisite repair and call it out explicitly in the handoff.

## Definition of a one-session milestone

A milestone should have:

- One primary technical objective.
- A bounded set of owned modules.
- No unresolved product decisions.
- Fewer than roughly ten meaningful implementation steps.
- Deterministic acceptance criteria.
- Tests runnable without private gameplay footage.
- A clean stopping point that leaves the main branch usable.

If the assigned work cannot meet those constraints, the agent should propose a split before implementing a partial architecture that another milestone must undo.

## Milestone dependency graph

```mermaid
flowchart TD
    M00[M00 Repository foundation] --> M01[M01 Contracts and versioning]
    M01 --> M02[M02 Database and migrations]
    M02 --> M03[M03 Worker lifecycle and job engine]
    M03 --> M04[M04 Media probing]
    M04 --> M05[M05 Safe import pipeline]
    M05 --> M06[M06 Fingerprints and duplicates]
    M05 --> M07[M07 Watched folders and Xbox flow]
    M05 --> M08[M08 Proxies thumbnails waveforms]
    M03 --> M09[M09 Desktop library and jobs UI]
    M08 --> M09
    M05 --> M10[M10 Phone QR upload]
    M09 --> M10
    M06 --> M11[M11 Session grouping]
    M11 --> M12[M12 Visual and audio overlap]
    M08 --> M12
    M09 --> M13[M13 Virtual session timeline]
    M12 --> M13
    M01 --> M14[M14 Detector SDK and profile schema]
    M08 --> M14
    M09 --> M15[M15 Profile calibration UI]
    M14 --> M15
    M15 --> M16[M16 Wanted-state detector]
    M15 --> M17[M17 Banner and subtitle detectors]
    M14 --> M18[M18 Audio analysis and transcription]
    M16 --> M19[M19 Event review and evaluation]
    M17 --> M19
    M18 --> M19
    M13 --> M19
    M12 --> M20[M20 Story engine]
    M19 --> M20
    M13 --> M21[M21 Editor project model]
    M21 --> M22[M22 Focused editor UI]
    M09 --> M22
    M18 --> M23[M23 Captions and audio controls]
    M22 --> M23
    M04 --> M24[M24 Render engine]
    M21 --> M24
    M14 --> M25[M25 HUD-aware vertical layouts]
    M22 --> M25
    M24 --> M25
    M02 --> M26[M26 Search and collections]
    M09 --> M26
    M19 --> M26
    M21 --> M27[M27 Open exports and manifests]
    M24 --> M27
    M17 --> M28[M28 Privacy and spoiler review]
    M18 --> M28
    M22 --> M28
    M24 --> M29[M29 Windows packaging and model manager]
    M03 --> M29
    M08 --> M29
    M18 --> M29
    M10 --> M30[M30 Security hardening and SBOM]
    M29 --> M30
    M22 --> M31[M31 Accessibility onboarding and docs]
    M29 --> M31
    M20 --> M32[M32 Windows public alpha qualification]
    M23 --> M32
    M25 --> M32
    M26 --> M32
    M27 --> M32
    M28 --> M32
    M30 --> M32
    M31 --> M32
    M24 --> M33[M33 macOS foundation and CI]
    M29 --> M33
    M18 --> M34[M34 macOS worker and media toolchain]
    M29 --> M34
    M33 --> M34
    M07 --> M35[M35 macOS files permissions and lifecycle]
    M10 --> M35
    M33 --> M35
    M34 --> M35
    M25 --> M36[M36 macOS media and render parity]
    M33 --> M36
    M34 --> M36
    M30 --> M37[M37 macOS signing notarization and DMGs]
    M34 --> M37
    M35 --> M37
    M36 --> M37
    M31 --> M38[M38 macOS UX accessibility and docs]
    M35 --> M38
    M37 --> M38
    M32 --> M39[M39 Dual-platform release qualification]
    M37 --> M39
    M38 --> M39
```

## Parallel work lanes

Once their dependencies are merged, the following milestones are intentionally parallel-safe:

- M06, M07, and M08 after M05.
- M10, M11, and continued library UI work after M09/M06.
- M16, M17, and M18 after M14/M15 as specified.
- M20, M21, M24, and M26 after their separate prerequisites.
- M23, M25, M27, and M28 once the editor model/UI is stable.
- M33 can begin after M24/M29 while independent product milestones continue.
- M35 and M36 may proceed in parallel after M34, but must coordinate bundle and capability contracts.

Parallel agents must not edit the same generated contract or migration without coordinating first.

## Copy/paste assignment prompt

Replace both occurrences of `MXX` before starting a session:

```text
Implement milestone MXX using docs/milestones/MXX-name.md.

Read AGENTS.md, README.md, OPENWORLD_MOMENTS_BUILD_SPEC.md, MILESTONES.md,
the complete MXX brief, and the merged handoffs of every dependency. Work only
within MXX scope. Satisfy every acceptance criterion, run and report all required
validation, update affected documentation, and finish with the repository's
milestone handoff. Do not start a dependent milestone or claim completion if any
required check is skipped.
```

## Milestone index

| ID | Milestone | Depends on | Primary output | Brief |
|---|---|---|---|---|
| M00 | Repository foundation | None | Buildable monorepo, CI, licenses, standards | [Open](./docs/milestones/M00-repository-foundation.md) |
| M01 | Contracts and versioning | M00 | Versioned JSON Schemas and generated types | [Open](./docs/milestones/M01-contracts-and-versioning.md) |
| M02 | Database and migrations | M01 | SQLite schema, migrations, repositories | [Open](./docs/milestones/M02-database-and-migrations.md) |
| M03 | Worker lifecycle and job engine | M02 | Authenticated worker IPC and durable jobs | [Open](./docs/milestones/M03-worker-lifecycle-and-jobs.md) |
| M04 | Media probing | M03 | FFprobe capability and normalized media metadata | [Open](./docs/milestones/M04-media-probing.md) |
| M05 | Safe import pipeline | M04 | Reference/managed imports and staging | [Open](./docs/milestones/M05-safe-import-pipeline.md) |
| M06 | Fingerprints and duplicate detection | M05 | Exact/fast/perceptual identity pipeline | [Open](./docs/milestones/M06-fingerprints-and-duplicates.md) |
| M07 | Watched folders and Xbox onboarding | M05 | Stable folder watcher and OneDrive flow | [Open](./docs/milestones/M07-watched-folders-and-xbox.md) |
| M08 | Proxies, thumbnails, and waveforms | M04, M05 | Derived-media pipeline with HDR handling | [Open](./docs/milestones/M08-derived-media.md) |
| M09 | Desktop library and jobs UI | M03, M05, M08 | First usable import/library experience | [Open](./docs/milestones/M09-library-and-jobs-ui.md) |
| M10 | Phone QR upload | M05, M09 | Temporary isolated LAN transfer | [Open](./docs/milestones/M10-phone-qr-upload.md) |
| M11 | Session grouping | M06 | Explainable metadata-based grouping | [Open](./docs/milestones/M11-session-grouping.md) |
| M12 | Visual and audio overlap | M08, M11 | Duplicate-time alignment and confidence | [Open](./docs/milestones/M12-overlap-alignment.md) |
| M13 | Virtual session timeline | M09, M12 | Unique-time playback across source files | [Open](./docs/milestones/M13-virtual-session-timeline.md) |
| M14 | Detector SDK and profile schema | M01, M03, M08 | Extensible detector/profile runtime | [Open](./docs/milestones/M14-detector-sdk-and-profiles.md) |
| M15 | Profile calibration UI | M09, M14 | ROI calibration and profile patches | [Open](./docs/milestones/M15-profile-calibration.md) |
| M16 | Wanted-state detector | M15 | First temporal GTA-aware detector | [Open](./docs/milestones/M16-wanted-state-detector.md) |
| M17 | Banner and subtitle detectors | M15 | OCR-based state/dialogue events | [Open](./docs/milestones/M17-banner-and-subtitle-detectors.md) |
| M18 | Audio analysis and transcription | M14 | Audio evidence and optional local words | [Open](./docs/milestones/M18-audio-and-transcription.md) |
| M19 | Event review and evaluation | M13, M16, M17, M18 | Evidence UI and reproducible metrics | [Open](./docs/milestones/M19-event-review-and-evaluation.md) |
| M20 | Story engine | M12, M19 | Explainable setup-to-payoff suggestions | [Open](./docs/milestones/M20-story-engine.md) |
| M21 | Editor project model | M01, M02, M13 | Non-destructive EDL, autosave, undo model | [Open](./docs/milestones/M21-editor-project-model.md) |
| M22 | Focused editor UI | M09, M21 | Trim/split/reorder playback interface | [Open](./docs/milestones/M22-focused-editor-ui.md) |
| M23 | Captions and audio controls | M18, M22 | Caption correction, mute, and gain | [Open](./docs/milestones/M23-captions-and-audio.md) |
| M24 | Render engine | M04, M21 | Validated FFmpeg rendering and presets | [Open](./docs/milestones/M24-render-engine.md) |
| M25 | HUD-aware vertical layouts | M14, M22, M24 | Safe crop, fit, and layout keyframes | [Open](./docs/milestones/M25-hud-aware-vertical-layouts.md) |
| M26 | Search and collections | M02, M09, M19 | FTS search, filters, and collections | [Open](./docs/milestones/M26-search-and-collections.md) |
| M27 | Open exports and manifests | M21, M24 | JSONL, captions, OTIO, and reproducibility | [Open](./docs/milestones/M27-open-exports-and-manifests.md) |
| M28 | Privacy and spoiler review | M17, M18, M22 | Review gates, blur regions, risk flags | [Open](./docs/milestones/M28-privacy-and-spoiler-review.md) |
| M29 | Windows packaging and model manager | M03, M08, M18, M24 | Installable signed-ready alpha package | [Open](./docs/milestones/M29-windows-packaging-and-models.md) |
| M30 | Security hardening and SBOM | M10, M29 | Threat-model closure, dependency inventory | [Open](./docs/milestones/M30-security-hardening-and-sbom.md) |
| M31 | Accessibility, onboarding, and documentation | M22, M29 | Keyboard-complete onboarding and user docs | [Open](./docs/milestones/M31-accessibility-onboarding-docs.md) |
| M32 | Windows public alpha qualification | M20, M23, M25–M31 | Windows release candidate and qualification report | [Open](./docs/milestones/M32-public-alpha-qualification.md) |
| M33 | macOS foundation and CI | M24, M29 | Native host builds, platform contract, dual-architecture CI | [Open](./docs/milestones/M33-macos-foundation-and-ci.md) |
| M34 | macOS worker and media toolchain | M18, M29, M33 | Native worker/FFmpeg bundles and model compatibility | [Open](./docs/milestones/M34-macos-worker-and-media-toolchain.md) |
| M35 | macOS files, permissions, and lifecycle | M07, M10, M33, M34 | Safe imports, watchers, storage, sleep/wake, and phone LAN flow | [Open](./docs/milestones/M35-macos-files-permissions-and-lifecycle.md) |
| M36 | macOS media and render parity | M25, M33, M34 | Playback, proxy, VideoToolbox, color, and render parity | [Open](./docs/milestones/M36-macos-media-and-render-parity.md) |
| M37 | macOS signing, notarization, and DMGs | M30, M34–M36 | Signed and notarized native DMGs | [Open](./docs/milestones/M37-macos-signing-notarization-and-dmg.md) |
| M38 | macOS UX, accessibility, and documentation | M31, M35, M37 | Native conventions, VoiceOver, onboarding, and guides | [Open](./docs/milestones/M38-macos-ux-accessibility-and-docs.md) |
| M39 | Dual-platform release qualification | M32, M37, M38 | Qualified Windows and macOS release assets | [Open](./docs/milestones/M39-dual-platform-release-qualification.md) |

## Required quality gates by lane

### Foundation and backend milestones

- Formatting and linting.
- Static type checks.
- Unit tests.
- Migration tests when storage changes.
- Contract compatibility tests when schemas change.

### Media milestones

- Synthetic fixture tests.
- FFprobe validation.
- Cancellation and failure-path tests.
- No source mutation.
- Paths with spaces, Unicode, and long names.

### Detector milestones

- Versioned fixture manifest.
- Precision/recall or explicit synthetic-case table.
- False-positive cases.
- Performance measurement.
- Evidence and confidence validation.

### UI milestones

- Keyboard path.
- Empty, loading, success, error, and cancelled states.
- Component tests.
- At least one end-to-end happy path.
- Screenshot or screen recording in the handoff when visual behavior changes.

### Release milestones

- Clean-machine validation on every claimed OS and CPU architecture.
- Dependency and license inventory.
- Upgrade/rollback behavior.
- Security review.
- Documented known limitations.
- Signature, notarization, Gatekeeper, checksum, and architecture verification where applicable.

## Milestone completion ledger

Each milestone pull request updates its own row **in the same pull request**, so the ledger changes exactly when the milestone merges. No separate ledger PRs.

- Set **Status** to `Complete`, link the **PR**, and fill **Completed by** and **Notes**.
- Leave **Commit** as `—`; the PR link records the merge commit.
- Change any milestone whose dependencies are now all complete to `Ready`.

| Milestone | Status | PR | Commit | Completed by | Notes |
|---|---|---|---|---|---|
| M00 | Complete | [#1](https://github.com/heetdalsania/openworld-moments/pull/1) | — | Arun Velkumar | Licenses pending maintainer confirmation; CI green on Linux + Windows |
| M01 | Complete | [#5](https://github.com/heetdalsania/openworld-moments/pull/5) | — | Arun Velkumar | JSON Schema 2020-12 contracts at schema_version 1.0; TS + Pydantic generated; CI drift check |
| M02 | Complete | [#6](https://github.com/heetdalsania/openworld-moments/pull/6) | — | Arun Velkumar | SQLite (WAL) schema v1 for all §9.7 tables; in-house migration runner with backups; typed repositories |
| M03 | Complete | [#7](https://github.com/heetdalsania/openworld-moments/pull/7) | — | Arun Velkumar | Rust supervisor + loopback token-auth FastAPI worker; durable jobs with WebSocket progress; contracts 1.1, migration 0002 |
| M04 | Complete | [#8](https://github.com/heetdalsania/openworld-moments/pull/8) | — | Arun Velkumar | FFprobe probe job (exact rationals, clockwise rotation, HDR side data, stable error codes), `doctor` + `/v1/capabilities`, synthetic fixtures; FFmpeg ≥ 6.0; contracts 1.2, migration 0003 |
| M05 | Complete | [#9](https://github.com/heetdalsania/openworld-moments/pull/9) | — | Arun Velkumar | Reference + managed imports (staging, atomic content-addressed promotion), idempotency keys, provenance, missing-source check, SHA-256-verified relink; contracts 1.3, migration 0004 |
| M06 | Complete | [#10](https://github.com/heetdalsania/openworld-moments/pull/10) | — | Arun Velkumar | Fast partial hash (no re-copy of known files, relink pre-check), versioned dhash256 head/tail frame and energy-envelope audio fingerprints, review-only duplicate candidates, restartable backfill; contracts 1.4, migration 0005 |
| M07 | Complete | [#12](https://github.com/heetdalsania/openworld-moments/pull/12) | — | Arun Velkumar | Rust watcher (notify + 15-min reconciliation, 10 s stabilization, offline backoff, cloud placeholders), worker-side folder settings and per-version file records with deduplicated imports, settings UI and Xbox/OneDrive onboarding; contracts 1.5, migration 0006 |
| M08 | Complete | [#13](https://github.com/heetdalsania/openworld-moments/pull/13) | — | Arun Velkumar | Explainable proxy policy; deterministic H.264 SDR proxies with LUT-based (lut3d, no zimg) HDR tone mapping; filmstrip JPEGs and owm-waveform peaks; versioned recipes and cache keys, atomic key-named promotion, FFprobe and sampled-decode validation, cancellable FFmpeg with progress, link-safe cleanup; contracts 1.6, migration 0007 |
| M09 | Complete | [#14](https://github.com/heetdalsania/openworld-moments/pull/14) | — | Arun Velkumar | App shell with Library and Settings; import by button or drag and drop; newest-first keyset-paged library; clip view playing proxy or original over an allow-listed `owm-media` Range protocol; automatic playback preparation; durable job center with live events, cancel, retry, readable errors; keyboard-complete; `worker_api` route allowlist; E2E import-to-playback test |
| M10 | In review | [#15](https://github.com/heetdalsania/openworld-moments/pull/15) | — | Arun Velkumar | Separate LAN gateway process on one chosen private address; 256-bit token, 10-minute expiry, closes with the screen; streamed uploads with extension, magic, size, count, and free-space checks into `staging/phone/<session>/NNNN/`; managed `phone_upload` imports; threat tests and E2E. **Pending: real-phone smoke test on a Windows private network** |
| M11 | Complete | [#16](https://github.com/heetdalsania/openworld-moments/pull/16) | — | Arun Velkumar | Capture-time estimator v1 (filename patterns, container, mtime; agreement/disagreement confidence, time-zone notes, copy artefacts); `owm-metadata-gap` v1 grouping (source, format, 15-min gap, import order) with per-join evidence; idempotent `group` job; merge/split/reorder/remove/confirm corrections with a log; synthetic fixtures; contracts 1.7, migration 0008 |
| M12 | Complete | [#18](https://github.com/heetdalsania/openworld-moments/pull/18) | — | Arun Velkumar | `owm-overlap` v1: dhash256 vote-and-verify alignment of A's tail with B's head (≥4 compared, ≥80% matching, ≥2 s unbroken run), ambiguity rejection for repeating footage, envelope cross-correlation refinement; applies only `matched` (≥0.6) or user overrides via the shared session layout; cached per pair and version; `align` job and override API; contracts 1.8, migration 0009 |
| M13 | Complete | [#19](https://github.com/heetdalsania/openworld-moments/pull/19) | — | Arun Velkumar | Pure source ↔ virtual time mapping (`timeline.ts`; round trips within one frame at 23.976–120 fps and VFR averages); two-element `SessionPlayer` that preloads the next clip at its first unique frame, switches at boundaries without replaying hidden overlap, keeps audio with the visible clip, and keeps the moment across reveal/reorder; Sessions and session screens with track, thumbnails, waveforms, overlap confidence, reveal toggle, keyboard controls, and reorder/split/remove/merge/override/confirm; session routes and PUT allow-listed in the host; E2E against the real worker |
| M14 | Complete | [#20](https://github.com/heetdalsania/openworld-moments/pull/20) | — | Arun Velkumar | Built-in detector runtime, immutable derived-frame SDK, bounded local JSON profile inheritance and compatibility, independently cached and cancellable runs, evidence/provenance validation, synthetic example and CLI; contracts 1.9, migration 0010; all local quality gates and the production build pass. |
| M15 | Complete | [#21](https://github.com/heetdalsania/openworld-moments/pull/21) | — | Arun Velkumar | Accessible upright ROI calibration from imported playback frames; sparse local overrides and base diff/reset, preprocessing and real synthetic SDK preview, safe JSON patch import/export and separate crop export; contracts 1.10, no migration. See [handoff](./docs/milestones/M15-handoff.md). |
| M16 | Complete | [#22](https://github.com/heetdalsania/openworld-moments/pull/22) | — | Arun Velkumar | Analytic star/disc ROI estimator, temporal changes, local crop references, replay/benchmark; contracts 1.11, SDK 1.1; synthetic FFmpeg validation only, game compatibility unvalidated |
| M17 | Complete | [#23](https://github.com/heetdalsania/openworld-moments/pull/23) | — | Arun Velkumar | Local ROI-only Tesseract banner/subtitle intervals, locale matching and line evidence/spoiler flags; contracts 1.12, SDK 1.2; synthetic validation, game compatibility unvalidated. See [handoff](./docs/milestones/M17-handoff.md). |
| M18 | Complete | [#24](https://github.com/heetdalsania/openworld-moments/pull/24) | — | Arun Velkumar | `audio-features` 1.0.0: first-stream proxy audio (8 kHz full + 300–3400 Hz band), onset/impact (±20 ms PCM, ±30 ms via AAC), silence, speech-like activity, all `role: supporting`; optional whisper.cpp transcription with explicit local model install (no downloads), per-clip cached/cancellable/resumable `transcribe` job, words in M13 session time, privacy notice and text-only delete in the session screen; contracts 1.13, SDK 1.3.0, migration 0011 |
| M19 | Complete | [#25](https://github.com/heetdalsania/openworld-moments/pull/25) | — | Arun Velkumar | Immutable observation snapshots and append-only review decisions, timeline markers/evidence/manual corrections, deterministic local holdout metrics and privacy-minimized compatibility reports; contracts 1.14, migration 0012. See [handoff](./docs/milestones/M19-handoff.md). |
| M20 | Complete | [#26](https://github.com/heetdalsania/openworld-moments/pull/26) | — | Arun Velkumar | `owm-story` 1.0.0 deterministic windows/beats, exact event revisions/source ranges, speech/scene/silence boundaries, duration presets/alternatives and decomposed scores; audited candidate decisions and preserved regeneration, CLI/API jobs; contracts 1.15, migration 0013. See [handoff](./docs/milestones/M20-handoff.md). |
| M21 | Complete | [#27](https://github.com/heetdalsania/openworld-moments/pull/27) | — | Arun Velkumar | Contracts 1.16 editor model, pure reversible commands, transactional autosave/recovery (0014), source relink and portable JSON, manual session selection; shared fixtures, property tests and process-crash validation. See [handoff](./docs/milestones/M21-handoff.md). |
| M22 | Complete | [#28](https://github.com/heetdalsania/openworld-moments/pull/28) | — | Arun Velkumar | Focused keyboard-accessible editor, M21 commands, retained autosave drafts/recovery, source-mapped playback and read-only context; synthetic Chromium and native worker E2E. See [handoff](./docs/milestones/M22-handoff.md). |
| M23 | Complete | [#29](https://github.com/heetdalsania/openworld-moments/pull/29) | — | Arun Velkumar | Contracts 1.17 caption settings, pure caption/audio commands, transcript source mapping, safe-area/protected-region preview, Unicode SRT/VTT and explicit native save, gain/mute preview and recovery. See [handoff](./docs/milestones/M23-handoff.md). |
| M24 | Complete | [#30](https://github.com/heetdalsania/openworld-moments/pull/30) | — | Arun Velkumar | Render IR (plan_version 1) compiled to argv-only FFmpeg graphs from saved editor revisions; full SHA-256 source verification; exact cumulative frame/sample trims (goldens exact, budget ±100 ms); fit/fill/manual crop keyframes, privacy blur, gain/mute ranges, HDR LUT tone map; text overlays/burn-in an explicit-omission hook; probed hardware encoders with quality notes and explicit CPU fallback; progress, cancellation, disk preflight, FFprobe/decode/black validation, atomic completion and manifest; contracts 1.18, migration 0015, editor Export panel |
| M25 | Complete | [#31](https://github.com/heetdalsania/openworld-moments/pull/31) | — | Arun Velkumar | Contracts 1.19 independent vertical variants, fit/blur and smooth fixed/keyed crops, calibrated HUD warnings and explicit versioned static suggestions; 1080×1920 renders, two-pixel geometry goldens and browser E2E. See [handoff](./docs/milestones/M25-handoff.md). |
| M26 | Complete | [#32](https://github.com/heetdalsania/openworld-moments/pull/32) | — | Arun Velkumar | Contracts 1.20 `search`, `search-index`, `collection`; migration 0016 trigger-maintained FTS5 index (secure-delete) over clips, sessions, effective events/OCR, transcript spans and projects; safe query grammar, filters, facets, ranking and timestamp results; keyboard search-to-playback; manual and rule collections with reasons; cancellable rebuild, stale/corrupt recovery, privacy clear; 10,000-clip p95 ≤ 138 ms on M4. See [handoff](./docs/milestones/M26-handoff.md). |
| M27 | Complete | [#33](https://github.com/heetdalsania/openworld-moments/pull/33) | — | Arun Velkumar | Contracts 1.21 `export-result`, `project-export`, `event-export` and extended `export-manifest`; migration 0017 stored render manifests; deterministic project JSON, event JSONL, SRT/WebVTT (byte-identical to the desktop), CSV markers with formula guard, OpenTimelineIO (validated with OTIO 0.18 and `otiostat`) and experimental FCPXML; warnings for unsupported operations and missing sources; paths only on explicit opt-in; host native save. See [handoff](./docs/milestones/M27-handoff.md). |
| M28 | Complete | [#34](https://github.com/heetdalsania/openworld-moments/pull/34) | — | Arun Velkumar | Contracts 1.22; migration 0018 hashed local review decisions; conservative OCR/caption/transcript/audio/spoiler findings, exact-range review, reversible choices, moving blur preview/render goldens, M23 mute suggestions, current-review gates for renders and project/caption/portable exports, and explicit text-only deletion. Required-tool gate, platform types, native build and synthetic Chromium walkthrough pass. See [handoff](./docs/milestones/M28-handoff.md). |
| M29 | In progress | [#35 (accepted plan)](https://github.com/heetdalsania/openworld-moments/pull/35) | — | — | GPL packaging policy accepted. Installer/model-manager implementation and clean Windows 11 validation are in progress; [handoff](./docs/milestones/M29-handoff.md). Not complete. |
| M30–M39 | See dependency graph | — | — | — | — |

## Scope-change procedure

If implementation reveals that a milestone is too large or invalid:

1. Stop before introducing a partial architecture.
2. Document the discovered constraint.
3. Propose new milestone boundaries and dependency changes.
4. Update the product specification only if product behavior changes.
5. Merge the planning change before restarting implementation.

This prevents separate agents from building against different assumptions.

