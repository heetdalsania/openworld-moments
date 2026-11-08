## Milestone handoff

- Milestone: M28 — Privacy and spoiler review
- Outcome: The editor surfaces local, explainable text/audio/spoiler findings with
  supporting ranges. Creators can seek evidence, acknowledge or reversibly ignore
  findings, attest a manual fix, mute selected audio ranges, and add moving blur
  rectangles. Current creator review gates new renders and project exports.
  Derived text and review data can be deleted without deleting source footage.
- Files and modules changed:
  - Worker `privacy/service.py`, `privacy/blur.py`, API routes, render compiler and
    gate/manifest integration, open-export gate and summary extensions.
  - Desktop `PrivacyPanel`, shared blur geometry/preview, editor retiming, caption
    sidecar integration, API client, styles and native route/command allowlist.
  - Contracts/synthetic fixtures, migration 0018 and its upgrade fixture, privacy,
    real-media, editor/native and export tests; architecture guides, README/ledger.
- Public contracts or migrations:
  - **Contracts 1.22:** `privacy-review` findings/config/decisions/summary; optional
    blur keyframes in Project/render IR; optional text-free `privacy_review` in
    render plans, manifests and export results. Project JSON and JSONL preserve it
    under `extensions`. Old 1.x documents remain readable.
  - **Migration 0018:** `privacy_reviews`, with spoiler configuration and hashed
    finding decisions; no copied OCR/transcript evidence is stored there.
  - GET/PUT/POST/DELETE `/v1/projects/{id}/privacy-review` and DELETE
    `/v1/projects/{id}/privacy-text`. The old ungated `caption_export` host command
    is removed; caption saves use `project_export` after autosave flush.
- Commands run: dependency ancestry and M26/M27 merged/green verification;
  `pnpm format`, `pnpm contracts:generate`,
  `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`; affected TypeScript
  lint/type/test checks; worker mypy for darwin/win32/linux; `pnpm build`;
  focused privacy/render/export/editor tests; deliberate `OWM_UPDATE_GOLDENS=1`
  export golden update; headed Chromium through the Playwright CLI skill and the
  temporary real-worker `tests/editor_browser.py --captions` bridge.
- Test and validation results: The full required-tool `pnpm check` passes: worker
  **1085 passed, 1 skipped** (the existing Windows-only junction test on macOS),
  Python contracts **336**, TypeScript contracts **364** and Rust **50**. Final
  affected TypeScript formatting/lint/types and the complete desktop suite
  (**244 tests**) pass after the final UI changes. Worker mypy passes for
  darwin/win32/linux (**198 files**), as does the final macOS arm64 production
  build. The existing Vite >500 kB chunk warning remains. No M28-required case
  is skipped. Focused privacy tests: **29 passed**.
  - Shared horizontal/vertical blur geometry and actual FFmpeg edges match within
    **two output pixels**. Blur strength, end-exclusive restoration, source
    SHA/mtime preservation and both aspect ratios pass.
  - Chromium: a phone/username caption, user spoiler label and manual range yield
    **11 findings**; exact-range mute, moving blur controls, false-positive ignore,
    checklist persistence/reload and aspect-edit invalidation pass. The reviewed
    **12,000 ms** horizontal render passes **13/13** media checks and records its
    review summary.
  - Confirmed UI text purge/reload: captions/transcript segments become **0**,
    recovery becomes null, source availability remains intact, and the two broad
    mixed-audio warnings remain. Temporary browser/worker/library processes were
    closed and removed afterward.
- Decisions made:
  - `conservative-review/1`: formatted phone candidates (0.70), explicit usernames
    (0.65), subtitles (0.60), literal user spoiler phrases (0.80), mission metadata
    (0.60), manual spoiler ranges (1.00), speech evidence (0.50), and possible mixed
    audio from metadata (0.35). These are heuristic scores, not probabilities.
    Bare scores, dates, coordinates and HUD digit runs do not match the phone rule.
  - Findings are computed in memory; only config and hashed choices persist.
    Tokens bind the saved revision/document, evidence, config and detector version.
    Changed inputs invalidate decisions. Unreviewed, stale, unresolved or unchecked
    states refuse export. “Fixed” is a creator attestation, not machine clearance.
  - Event JSONL includes whole-session evidence, so findings outside the cut are
    also reviewed, explicitly linked in session time. Unproven old OCR timing uses
    conservative retained-source coverage, labelled as such.
  - Blur coordinates are output normalized. Fixed dimensions, linear translation,
    first key at zero, strict ordering, last-key hold, half-open activation,
    chroma-aligned pixels and an 8-pixel minimum; max 100 keys per region.
    Trim/split/reorder preserve retained trajectories and Undo restores them.
    Preview uses the existing decoder; its blur kernel is approximate. New moving
    blurs stamp the current contract version. Render engine **1.2.0**.
  - Review controls disable while their document is unsaved or stale. Actions fetch
    fresh findings after a flush changes the revision; regression tests cover this
    browser-discovered refresh race and retained partial checklist acknowledgment.
- Necessary prerequisite correction: open exports now read the project and evidence
  through the same SQLite snapshot, required to bind review to the exported data.
  An existing Search keyboard test captured initial empty-query rows before the
  200 ms debounced request finished. It now waits for the requested query before
  asserting focus, preventing a later result replacement from racing the test.
  The brief's nonexistent spec 18.4/21.4 references were corrected to the actual
  privacy/publishing sections; no architecture or scope expansion was needed.
- Known limitations:
  - No identity recognition, guaranteed PII detection, legal clearance, automatic
    censorship or speaker/track separation. Missing OCR/transcripts reduce coverage;
    formatted HUD numbers, dialogue/music and subtitles can produce false positives.
    Real gameplay detection and real whisper.cpp recognition remain unmeasured.
  - Manual spoiler ranges need rechecking after timeline edits. Blurs apply in each
    output frame, so review every aspect ratio and the actual rendered appearance.
    Blurs and mutes do not redact caption/metadata exports or apply effects in a
    third-party editor. Plain caption/CSV/FCPXML files do not embed review summaries;
    their API envelopes carry them. Old manifests remain frozen and re-exportable.
  - Text purge covers the session's transcript/current and historical text evidence,
    caches, this project's copied text/recovery and review config. FTS updates in the
    same transaction. Active analysis/transcription must finish or be cancelled.
    Other projects, prior exports, backups and filesystem snapshots may retain
    copies; remove those separately. No physical secure-erasure claim is made.
  - M10's real-phone Windows smoke test, unvalidated GTA profiles and official macOS
    qualification remain outstanding from earlier milestones.
- Follow-up milestones affected: **M29** Windows packaging/model manager is next;
  M30/M31/M32 should include review/deletion/blur flows in reliability, accessibility
  and release qualification. No later milestone is implemented here.
- Screenshots, reports, or artifacts: [privacy architecture](../architecture/privacy-review.md),
  shared `fixtures/synthetic/privacy-blur-v1.json`, and executable tests. Ignored
  local `output/playwright/m28-review.png`, `m28-preview.png` and
  `m28-vertical-preview.png` record the synthetic Chromium walkthrough. No secrets,
  private paths, source footage, models, databases or build outputs are committed.

- Pull request: [#34](https://github.com/heetdalsania/openworld-moments/pull/34).
