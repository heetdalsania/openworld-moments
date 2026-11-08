# M21 — Editor project model handoff

## Milestone handoff

- Milestone: M21 — Editor project model
- Outcome: Versioned non-destructive editor documents, pure timeline operations and
  bounded undo/redo, transactional revision-checked autosave/recovery, manual
  session-selection creation, portable JSON and explicit source relinking.
  Visual timeline editing and rendering remain M22/M24.
- Files and modules changed: `apps/desktop/src/editor.ts`, `projectAutosave.ts`,
  typed API client and Rust route allow-list; worker `projects/service.py` and
  project API routes; shared schemas/generated types/semantic validation and
  fixtures; migration 0014 and upgrade fixture; desktop/worker regression tests;
  architecture guide, contracts changelog, README and milestone ledger.
- Public contracts or migrations: Contracts **1.16**, new `editor-project` model
  version 1; additive Project text overlays and audio gain ranges. SQL
  `0014_editor_projects.sql` stores current/previous committed documents and save
  revision, linked to existing Story/Project IDs. New project API routes are
  documented in [editor projects](../architecture/editor-projects.md).
- Commands run: dependency ancestry checks for merged M01 PR #5, M02 #6 and M13
  #19; branch from merged main `a53b2aafb90e582e9aae316c001180fa87ea3eaa`;
  `pnpm contracts:generate`, `pnpm format`, focused desktop/worker/contract tests,
  `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`, platform mypy checks and
  `pnpm build`. Final validation results are recorded below before PR handoff.
- Test and validation results: Full required-tool `pnpm check` passed: worker
  **925 passed, 1 skipped** (existing Windows-only junction test on macOS), Python
  contracts **238 passed**, TypeScript contracts **257 passed**, desktop **159 passed**
  and Rust **47 passed**. Focused project/migration tests **40 passed**, focused
  command/autosave tests **12 passed**. Windows/Linux mypy passed (152 worker source
  files); native macOS arm64 production build passed. Existing >500 kB chunk warning
  remains. Staged-file audit found no private paths, secrets, media, models,
  databases or build outputs. Hosted CI is recorded in the PR before owner handoff.
- Decisions made: Strict finalized editor rules live in a new envelope so legacy
  1.x Project documents stay readable. Explicit migration preserves all existing
  edits and refuses unsupported layouts. Commands ripple one primary track;
  annotations follow retained source content and crops hold between keyframes.
  Undo uses exact snapshots, defaults to 100 commands and caps retained serialized
  snapshots at 16 MiB while retaining the latest command. Autosave defaults to
  750 ms, serializes saves and retains dirty state on failure. Save and Story
  `edited` state commit atomically; stale revisions cannot overwrite newer saves.
  Portable import requires explicit local source choices and per-source hash
  replacement confirmation; relink preserves project identity and recovery.
- Known limitations: In-memory undo history resets on reopen; the committed EDL
  and previous recovery snapshot persist. UI integration, visual cancellation,
  source chooser/confirmation controls and rendering are downstream. Availability
  is path/size plus metadata, labeled `available_unverified`; explicit import/relink
  reads full hashes, and M24 must verify referenced originals before rendering.
  Synthetic byte files and a subprocess crash establish model/transaction
  behavior, not real-game editing, playback or power-loss durability. Existing
  M10 real-phone Windows verification, unvalidated GTA profiles and real whisper
  recognition remain outstanding. No source media or generated media committed.
- Follow-up milestones affected: **M22** focused editor UI and **M24** render engine
  have their dependencies after M21 merges. M23/M25/M27/M28 consume the documented
  annotations, layout, source identity and renderer-facing document. M20 generation
  remains independent and cannot overwrite editor-owned stories.
- Screenshots, reports, or artifacts: No visual UI change, so no screenshots.
  Architecture and migration policy: [editor projects](../architecture/editor-projects.md).
  Executable shared fixtures: `packages/contracts/fixtures/editor-project/`.
  Property test seed `0x21`, 150 sequences of up to 60 commands. Hosted CI and PR
  links are added on handoff; the PR remains unmerged for owner review.
