# M23 — Captions and audio controls handoff

## Milestone handoff

- Milestone: M23 — Captions and audio controls
- Outcome: Transcript-backed/manual caption correction, add/remove/split/merge and
  retiming; style/placement and burn-in/sidecar intent; protected-region warnings;
  Unicode SRT/VTT with explicit native save; project/cut/range gain and mute,
  waveform shading and real audio preview, through M21 commands/undo/autosave.
- Files and modules changed: `CaptionPanel`, `AudioPanel`, `captions.ts`,
  `editorAudio.ts`, editor commands and `EditorView` preview integration; native
  `caption_export` registration/handler and typed API; shared contract schema,
  generated types, validators, version policy and fixtures; golden sidecars,
  component/unit tests, worker persistence test and optional manual browser fixture
  transcription; architecture guides, README and ledger.
- Public contracts or migrations: Contracts **1.17**, optional
  `Project.caption_settings {preset, region, burn_in, sidecar}`. Output-frame
  normalized region; high-contrast/compact presets; none/SRT/VTT/both output intent.
  Existing caption/audio units and model version 1 remain; no SQL migration.
  Explicit `captions`, `caption-settings` and `audio` commands extend M21.
  Native `caption_export {text, format}` accepts no destination path; a save dialog
  plus exclusive creation protects existing files. No worker endpoint added.
- Commands run: M18 #24 and M22 #28 confirmed merged and ancestors of branch base
  `dd425d1c6597050d4faead2405439ec33d40efb7`; `pnpm contracts:generate`,
  `pnpm format`, focused/full desktop and contract tests, worker project tests,
  required-tool `pnpm check`, platform mypy and `pnpm build`. Playwright CLI headed
  Chromium against temporary synthetic FFmpeg media, real worker persistence and
  M18 whisper.cpp test-double transcript; accessibility-tree/keyboard form review.
- Test and validation results: Final required-tool `pnpm check` passed: worker
  **929 passed, 1 skipped** (existing Windows-only junction case on macOS),
  Python contracts **241 passed**, TypeScript contracts **260 passed**, desktop
  **193 passed** and Rust **48 passed**. Windows/Linux platform mypy passed
  (154 source files), as did the final macOS arm64 production build and formatting.
  One unchanged phone-countdown test initially hit a timing failure; its targeted
  recheck and the complete default rerun passed. Fresh worker imports were also
  blocked by macOS `UF_HIDDEN` on the two local editable-package `.pth` files;
  clearing that flag restored imports and the complete default gate passed.
  Focused caption/audio/editor tests passed; full desktop **193 passed**,
  Python contracts **241 passed**, TypeScript contracts **260 passed**, worker
  project persistence **19 passed**. Chromium copied four transcript cues,
  corrected a Unicode/multiline cue through keyboard activation, muted the first
  cut, set +6 dB gain, enabled burn-in and both sidecars, and restored exact state
  on full reload. Configured mission-banner overlap warned; middle
  placement cleared it and survived another reload. The final-source browser
  repeat also verified unapplied caption/trim drafts across an audio command. The accessibility
  tree names every caption/audio field; component tests exercise cancellation,
  error/retry, keyboard isolation, warning and native-save outcomes.
  Web Audio measurements: muted interval gain/RMS **0/0**; unmuted gain
  **1.995262265** (+6 dB) and active RMS **0.12243549**, with context running.
  Measurement analysers sit after real app gain nodes; a final zero-gain test node
  silenced speaker output. Browser console had no errors/warnings. The first
  repository gate found source/vendored schema formatting drift; regeneration
  corrected it. An independent FFmpeg reader also verified the SRT golden file
  preserves raw ampersands and Unicode. No M23-required case was skipped.
- Decisions made: All cue/audio writes use M21 commands; successful new commands
  write contract 1.17 while undo restores exact previous snapshots. Caption
  operations sort by start/end and preserve existing overlap semantics. Source
  coordinates map transcript copies into repeated/reordered cuts. Replacing
  existing captions is explicit; cancellation, navigation or concurrent edits
  reject a pending replacement. Caption/profile data share calibration caches.
  Preview fits protected source regions into output coordinates. Mute dominates;
  range gain overrides project gain. Partial clears preserve outside pieces.
  Caption/audio edits do not restart playback. A small required M22 prerequisite
  repair resets trim forms by actual cut ranges instead of cloned object identity;
  caption forms use the same content-change rule. This preserves unapplied drafts
  across unrelated commands while keeping undo exact and keyboard focus intact. Sidecars export the current local
  text through a native destination choice, without overwriting existing files.
- Known limitations: Transcript copies remain in projects after source transcript
  deletion; this is stated in the UI. Real speech recognition/game compatibility
  remains unmeasured. Overlapping cues are retained; very long cues may clip in a
  small preview. The sidecar parser covers the emitted plain-text subset, not
  arbitrary WebVTT/SRT styling/import UI. SRT is raw text and some external
  players interpret HTML-like tags; VTT escapes literal markup. Blank/control lines must be corrected or
  split before sidecar export; project text is retained. Protected-region guidance
  uses the current upright fit preview; final crops/compositing/rendering are M24/M25.
  Native codecs, native screen-reader speech and the OS save-dialog interaction
  were not driven by Chromium; form review used its accessibility tree and keyboard
  tests, and save outcomes use a fake host plus existing exclusive-writer tests.
  Audio uses the first stream and cannot separate mixed voice/music/gameplay;
  +gain may clip. Preview range updates follow playback/frame callbacks and may
  lag during throttling/buffering; exact output audio belongs to M24. Existing
  unsaved-draft/process-exit and source-availability limitations still apply. The
  production bundle retains the existing large-chunk warning.
- Follow-up milestones affected: **M24 — Render engine** is next and must consume
  caption placement/style/burn-in and audio ranges. M25 adds final crop/layout
  parity; M27 uses sidecar state; M28 can propose explicit mute ranges. M26 and M28
  remain Ready under the current dependency graph. No later milestone implemented.
- Screenshots, reports, or artifacts: Local ignored `output/playwright/m23-editor.png`,
  `m23-protected-warning.png`, `m23-accessibility.txt` and `m23-audio-report.json`.
  Reproducible manual fixture: `tests/editor_browser.py --captions` (real worker,
  synthetic video and M18 fake recognition only). Temporary media/library/model
  were removed after capture. Golden text files are committed under
  `apps/desktop/src/testing/`; no footage, real models, libraries, databases,
  generated media, secrets or build outputs are committed. Hosted links added
  before handoff.
