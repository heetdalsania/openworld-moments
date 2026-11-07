## Milestone handoff

- Milestone: M17 — Banner and subtitle detectors
- Outcome: Two built-in producers recognize only calibrated banner/subtitle
  regions with optional local Tesseract. Known locale vocabulary maps to generic
  failure/arrest/mission events; unknown text remains raw low-confidence OCR.
  Persistent text emits one confirmed interval with line evidence and source
  times. Mission text carries spoiler-risk metadata without story interpretation.
  All quality evidence is synthetic; game compatibility remains unvalidated.
- Files and modules changed:
  - Worker `detectors/ocr.py`, `text.py`, `text_fixtures.py`, `text_benchmark.py`;
    shared analyzer, ROI sampler, SDK version and `owm text` CLI.
  - Profile/evidence contracts, generated TS/Pydantic and vendored schemas,
    version readers, cross-runtime valid/invalid fixtures.
  - `profiles/generic-text/`, `fixtures/manifests/text-v1.json`, detector guide,
    ADR-0005, architecture/profile/fixture/contract docs, README and ledger.
  - Temporal/parser/preprocessing/runtime failure/cache/cancel tests, real local
    OCR/FFmpeg/calibration/job/API/CLI/source-preservation tests; CI OCR setup.
- Public contracts or migrations:
  - Contracts **1.12**, additive: optional bounded `DetectorSettings.ocr`,
    installed `LocalePack.ocr_language`, and `OcrEvidence.frame_ms`/`lines`.
    Each line has text, normalized global source region and confidence; TS/Python
    enforce containment in its parent ROI. Prior 1.x fixtures remain readable.
    No database migration or new API route.
  - SDK **1.2.0**; OCR sampler **gray-roi640x128-2fps-v1**. Existing whole-frame
    and wanted samplers retain their dimensions and behavior.
  - Producers `region-banner-ocr` and `region-subtitle-ocr` **1.0.0**. Events:
    `openworld.failure`, `openworld.arrest`, `openworld.mission_started`,
    `openworld.mission_objective`, `openworld.mission_completed`,
    `openworld.mission_failed`, `openworld.ocr_text`, `openworld.subtitle`.
  - Source provenance/cache records engine version, language, locale ID/version,
    language-data SHA-256, preprocessing and sampler versions. The complete
    resolved profile/calibration/settings and session layout also enter identity.
  - CLI: `owm text doctor [--language eng]`,
    `owm text benchmark [--samples 60] [--repeats 3]`; existing analyze accepts
    `--profile generic-text`. No automatic engine/model download.
- Commands run:
  - `uv sync --all-packages --locked`, `pnpm contracts:generate`, `pnpm format`.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - `pnpm build` (production macOS arm64 desktop, no installer).
  - Worker `mypy --platform win32`, `--platform linux`, normal darwin checks.
  - Focused detector/runtime/media tests, and final changed temporal/provenance
    regression checks.
  - `owm text doctor`; `owm text benchmark --samples 60 --repeats 3`.
- Test and validation results:
  - Full local quality gates pass: formatting, ESLint/Clippy/Ruff, REUSE,
    TypeScript/mypy, tests and deterministic generated-contract drift. Worker
    **809 passed, 1 skipped** (existing Windows-only junction case on macOS);
    Python contracts **171**, TypeScript contracts **180**, desktop **130** and
    Rust **47** tests pass. No M17-required automated case skipped.
  - Production desktop build passes on macOS arm64 (no installer), with the
    existing Vite >500 kB chunk warning. Worker mypy passes for darwin, win32
    and linux. Hosted Linux/Windows CI is a separate PR check.
  - Six banner categories × base/small/dim-contrast/outline/duplex/multiline:
    **36/36** real-engine classifications with OCR confidence ≥0.75.
  - Real H.264 at **720p CRF18**, **1080p CRF30/70% brightness/outline** and
    **4K CRF32**: exactly three banner intervals (mission-completed, unknown OCR,
    arrest) and two subtitle intervals. Multiline dialogue stays one interval
    from 1000–3000 ms, replaced text spans 3000–5000 ms; evidence retains two line
    boxes and an explicit visible speaker prefix. Source SHA-256/mtime unchanged.
  - Banner text outside the configured ROI produces no banner event; moving the
    saved calibrated ROI yields the three expected banner intervals.
  - Persistent text, short flicker, brief/sustained misses, reappearance, gaps,
    clip end, model changes, unknown/ambiguous/low-confidence text, malformed TSV,
    timeout/cancel cleanup and old-success preservation have deterministic tests.
    Known OCR spelling variants deduplicate; distinct configured phrases remain
    separate intervals. Missing OCR skips its units explicitly.
  - Local reference benchmark: **Apple M4/macOS arm64/Python 3.12.14**,
    Tesseract **5.5.4**, OpenCV **4.14.0**, English model SHA-256
    `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`.
    Three runs over **60 moments / 30 synthetic seconds**, each with uncached
    banner and subtitle OCR (**120 calls/run**): 11.969, 11.419 and 11.584 s;
    median **11.584 s**, **2.590× real time**. Final repetition **120/120** exact
    OCR texts and **60/60** banner categories, including unknowns. Meets the 2×
    processing target on this reference machine; excludes proxy/decode/I/O,
    minimum Windows CPU and real-game accuracy. No held-out gameplay metric claimed.
  - CI follow-up: Windows initially rejected a distribution version with a leading
    `v` before recognition ran. Accept that prefix while retaining the >=5 gate;
    regression tests cover both reported formats and reject 4.x with either form.
    CI now runs the media-free OCR doctor before its full worker suite.
- Decisions made:
  - Optional Tesseract 5+ executable with explicitly installed language data;
    Apache-2.0 engine/official data. Runtime adds no Python dependency. M29/M34
    own packaging, model catalog and shipped notices/architecture qualification.
  - Extend the existing trusted ROI sampler to fixed 640×128 text crops, with
    dimension-aware reuse and an 80×16 proxy-detail guard; retain the existing
    64 MiB/600-second limits. No full source frame/path reaches OCR.
  - Banner contrast and subtitle midpoint-threshold preprocessing normalize
    grayscale, invert dark backgrounds and add an 8-pixel border. Fixed local
    argument arrays, owned temporary PGM, bounded TSV, timeout/cancel and cleanup.
    Check model metadata during reads and rehash before computed results commit.
  - English pack `en` 1.0.0 uses original generic phrases. Whole-text normalized
    fuzzy threshold 0.9, category margin 0.08, exact short phrases, OCR ≥0.75 for
    known categories; recognized unknown confidence capped at 0.49. Default text
    threshold 0.6, two supporting samples and one tolerated missing sample.
    These are explainable heuristic scores, not calibrated probabilities.
  - Development-only OpenCV/NumPy render synthetic Simplex/Duplex strokes. No font
    files are redistributed; OpenCV retains BSD terms for its Hershey renderer.
    Model/engine/font/game assets and generated media are excluded from Git.
- Known limitations:
  - Initial English synthetic pack only. Game HUDs, fonts, other languages,
    animation, background interference and gameplay precision/recall are unvalidated.
    Very similar subtitle text can merge under the 0.94 deduplication threshold.
  - Two fps gives coarse timing, can miss brief text and resets per asset.
    This does not provide exact word timing or cross-clip text continuity.
  - Existing 64 MiB raw-frame cap allows about **6.8 minutes per asset** with the
    text sampler. Streaming/chunked long-asset analysis is future work.
  - Missing engine/data explicitly skips OCR while other producers stay usable.
    Recognized text can be private/spoiler-sensitive; it stays local, without
    automatic logging/upload. No lawful gameplay capture was selected or searched.
  - M15's SDK preview remains the bright-region example; OCR evidence/review UI is
    M19. Physical Windows use, installers and packaged-model validation are separate.
    M10's real-phone Windows private-network smoke test remains pending.
- Follow-up milestones affected:
  - M18 is next; M21 is independently ready. M19 still waits on M18 and owns event
    review/corrections/evaluation. M28 consumes mission spoiler-risk metadata.
    M29/M34 qualify bundled OCR dependencies, models and platform architectures.
- Screenshots, reports, or artifacts:
  - [Text detector guide](../detectors/text.md), [ADR-0005](../architecture/adr/0005-local-ocr.md),
    [fixture manifest](../../fixtures/manifests/text-v1.json) and executable tests
    reproduce the synthetic case table and benchmark. Scratch reports/media
    remain outside Git. No visual product change or new screenshot required.
  - No secrets, user libraries, private paths, footage, models, databases, build
    outputs or generated media are included in this PR.
