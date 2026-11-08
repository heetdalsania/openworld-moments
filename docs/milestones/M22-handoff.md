# M22 — Focused editor UI handoff

## Milestone handoff

- Milestone: M22 — Focused editor UI
- Outcome: Projects browser, manual session-range creation and a single-track
  visual editor with source-mapped preview, filmstrip/waveform, trim handles and
  numeric times, split/remove/reorder, undo/redo, autosave/recovery, keyboard
  alternatives, read-only context and aspect-frame placeholders.
- Files and modules changed: desktop `EditorView`, `ProjectsView`, `CreateProject`,
  `projectWorkspace`, `projectTimeline`, `projectMedia`, shared `TimelineWave`;
  app/hash routing, styles and API client; existing player cut identity handling;
  worker project metadata discovery routes and Rust allow-list; component,
  mapping, worker and host E2E tests plus manual synthetic browser fixture;
  architecture guides, README and milestone ledger.
- Public contracts or migrations: No version/schema/migration changes. Additive
  GET `/v1/projects?limit=&offset=` and
  `/v1/sessions/{id}/project-selection` metadata endpoints. Existing M21 command,
  save/CAS and source identity rules remain authoritative. See
  [focused editor](../architecture/focused-editor.md).
- Commands run: Verified merged M09 #14 and M21 #27 ancestry before editing;
  branched from `d21097bfd500f0af2963d092f89dcd4eeb1de99a`. `pnpm format`,
  focused Vitest/pytest/native E2E, required-tool `pnpm check`, Windows/Linux
  platform mypy and `pnpm build`; Playwright CLI headed Chromium against temporary
  synthetic FFmpeg sources and a real worker using the test IPC/Range bridge.
- Test and validation results: Full required-tool `pnpm check` passed: worker **927 passed,
  1 skipped** (existing Windows-only junction test on macOS), Python contracts
  **238 passed**, TypeScript contracts **257 passed**, desktop **177 passed** and
  Rust **48 passed**. Windows/Linux worker mypy passed (153 source files), as did
  the native macOS arm64 production build and final formatting checks. An initial
  run hit the existing watched-file duplicate-report timing test; its unchanged
  recheck and the complete default rerun passed. Staged-file audit was clean.
  Focused editor/mapping **18 passed**, worker project **18 passed** and native
  editor create/trim/split/reorder/reopen passed. Chromium completed manual create
  (1000–10000 ms), trim in to 2000, split at 1000, keyboard reorder, autosave and
  full reload (revision 4, three exact source ranges). Decoded frame callbacks
  measured **0 ms** error at project 3000/source 2000 ms (reordered cuts of the
  same source) and project 4000/source 0 ms (next source), within one 30 fps frame
  (33.33 ms). Portrait placeholder measured 208.125 × 370 px (exact 9:16).
  This proves synthetic Chromium UI/media behavior; native host E2E separately
  proves worker API persistence/restart and unchanged source bytes.
- Decisions made: Every model edit uses M21 commands, with frozen visible
  snapshots. Retain dirty drafts across navigation/worker failures; serialized
  750 ms saves expose errors and recovery JSON. Stable cut IDs disambiguate
  repeated source instances. Small prerequisites repaired for this acceptance:
  project list/selection metadata, retained-cut playback clamping, and skip-link
  focus without destroying the hash route. Waveforms redraw after ripple duration
  changes. Read-only context requires current matching session layout and is
  remapped into retained source windows. No detector success is required.
- Known limitations: In-memory undo and unsaved drafts do not survive process
  termination; save or copy recovery JSON before reloading after a failure.
  Revision conflicts require explicit recovery/reopen, with no automatic merge.
  Ten retained/pending workspaces maximum; only clean histories are evicted.
  Native codecs and decoder buffering vary; frame stepping uses average rate for
  VFR. Synthetic frame results do not establish real-game/native WebView precision
  or gapless playback. Preview fits the aspect frame but does not render final
  crops, annotations or audio edits. Event context inspects the first 50 items,
  labelled in the UI. Original fallback uses existing `available_unverified`
  metadata; M24 must verify actual originals before render. Portable binding
  choices remain available through M21 API, without a new import/relink dialog.
  Existing M10 Windows phone smoke test and real-game/whisper quality remain
  unverified. Production build retains the existing large-chunk warning.
- Follow-up milestones affected: **M23** captions/audio is the next milestone;
  M24 rendering, M26 search/collections and M28 privacy review have prerequisites.
  M25 consumes this placeholder after M24. No later milestone implemented here.
- Screenshots, reports, or artifacts: Local ignored
  `output/playwright/m22-editor.png`, `m22-portrait.png` and
  `m22-precision.json`; manual fixture source
  `services/media-worker/tests/editor_browser.py`. Browser sources/library were
  temporary and removed after capture. Generated media, model binaries and
  libraries are not committed. [PR #28](https://github.com/heetdalsania/openworld-moments/pull/28) and
  [its CI checks](https://github.com/heetdalsania/openworld-moments/pull/28/checks)
  record hosted validation for the final head before merge.
