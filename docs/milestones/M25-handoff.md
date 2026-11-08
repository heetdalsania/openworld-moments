# M25 — HUD-aware vertical layouts handoff

## Milestone handoff

- Milestone: M25 — HUD-aware vertical layouts
- Outcome: Independent editable 1080×1920 variants on the existing project: complete
  frame fit, solid/blurred background, fixed crop and smooth keyed translation;
  effective profile overlays, protected-region warnings and explicit conservative
  framing suggestions. Vertical renders use M24's real pipeline and leave both
  original footage and horizontal crop settings intact.
- Files and modules changed: Shared project/profile/render schemas, generated
  contracts and fixtures; desktop layout controls, canvas preview, command/history
  integration and Export review; worker numeric layout planner, render graph,
  metadata/profile preflight and foreground validation; vertical preset JSON;
  shared geometry goldens, UI/unit/media tests and manual browser fixture routes;
  architecture/profile/preset guides, README and milestone ledger.
- Public contracts or migrations: Contracts **1.19**, additive
  `Segment.vertical_crop` (`layout_version: 1`), static suggestion provenance,
  profile `subject_hints`, optional render-piece geometry/effective profile and
  request `review_layout`/`expected_revision`. Editor model and render plan remain
  version 1. No SQL migration. No new API route, dependency or executable plugin.
- Commands run: Verified merged dependency ancestry M14 #20, M22 #28 and M24 #30
  against base `7a4233c659b54516354508be8170ddfb822e725c`; read their handoffs and
  M24's final successful hosted run. Contract generation; formatting; focused
  Vitest/pytest; required-tool `pnpm check`; worker mypy for Windows/Linux;
  `pnpm build`; Playwright CLI headed Chromium against a real worker and generated
  synthetic sources.
- Test and validation results: Required-tool `pnpm check` passes in full:
  **981 worker passed, 1 existing Windows-only junction skip on macOS**;
  Python contracts **270**, TypeScript contracts **291**, desktop **212**, Rust
  **48** passed. Windows/Linux mypy (166 files) and the native macOS arm64
  production build pass; the existing large-chunk warning remains. The final
  repository formatting, lint, types, all tests and generated drift gate pass.
  Earlier runs caught the old three-preset catalog expectation and a stale future
  schema-version fixture; both now cover the expanded catalog/contracts. Local
  hidden flags on editable Python package links also needed repair before the
  fresh full run; no import workaround was added to the repository. Focused FFmpeg tests already pass fit/blur,
  fixed/keyed marker edges within **2 output pixels**, portrait/rotation, source
  preservation and cancellation. Chromium created a two-cut 12-second project,
  selected a profile and vertical preview, authored fixed and moving keys, showed
  mission/subtitle warnings, explicitly reviewed and rendered **1080×1920** with
  **13/13** checks passing. Reload retained revision 5, two keys and both unchanged
  horizontal fit crops. Canvas audit confirms a real 1080×1920 backing surface
  containing decoded source pixels; browser console has zero errors/warnings.
- Decisions made: Absent vertical settings mean complete-frame fit. Crop dimensions
  remain fixed; smoothstep interpolates positions and holds outside keys. Static
  `static-profile/1` suggestions use only profile regions, never sampled motion:
  feasible crop confidence 0.65, conservative fit confidence 0.25, explicitly
  heuristic and saved only after user acceptance. Missing/incompatible/conflicted
  profiles warn; manual editing still works. More than 5% protected-region removal
  or possible blur coverage warns. Blur checking uses a conservative swept envelope
  so narrow crossings between keys are not missed. Explicit vertical review clears
  after edits; saved revision changes refuse the render. Details and coordinates
  are documented in [vertical layouts](../architecture/vertical-layouts.md).
- Small prerequisite adjustments: Vertical letterboxing requires foreground-only
  black-frame comparison in M24 validation; horizontal validation stays intact.
  Updated M24's preset-catalog assertions for the two new presets and the caption
  panel's obsolete “rendering arrives in M24” copy for current export behavior.
  After the full gate, legacy safe-mode copy and the render guide were clarified;
  focused render-plan tests, Ruff and formatting were rechecked.
- Known limitations: No face/object/action tracking; conflicting HUD zones generally
  require fit. Confidence is not calibrated gameplay accuracy. Canvas blur/color
  and proxy scaling can differ from the original-quality render; crop geometry is
  the parity contract. Trimming/splitting reanchors easing and can change its speed
  between retained anchors. Maximum 100 keys per cut and M24's 120 input limit;
  excessive changes are refused. Plan notices are bounded to 20 with an explicit
  additional-notices summary; the editor lists all crop warnings. Privacy blur
  and unsupported text are not previewed. M24's explicit text-omission hook and
  library-contained outputs remain. Native WebView/real-game framing, M10's
  Windows phone smoke and real whisper recognition remain unqualified.
- Follow-up milestones affected: **M26 — Search and collections** is next. M27
  open exports, M28 privacy review and M29 Windows packaging remain Ready; M36
  later consumes vertical geometry for native macOS media qualification.
- Screenshots, reports, or artifacts: Text-only shared
  `fixtures/synthetic/vertical-layout-v1.json`; local ignored
  `output/playwright/m25-crop-warning.png`, `m25-render-ready.png`,
  `m25-audit.txt` and `m25-render-report.txt`. No footage, models, user libraries,
  databases, secrets, private paths, generated media or build outputs are committed.

- Pull request: [#31](https://github.com/heetdalsania/openworld-moments/pull/31).
