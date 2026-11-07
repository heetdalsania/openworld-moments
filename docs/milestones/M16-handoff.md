## Milestone handoff

- Milestone: M16 — Wanted-state detector
- Outcome: The built-in `wanted-indicators` detector estimates zero through a
  configured maximum from a calibrated analytic star/disc row. Stable changes
  emit evidence-backed escalation/de-escalation events with confirmation,
  tolerated unknowns and debounce. Local replay provides sample traces and
  optional separate evidence crops. Game compatibility, including GTA VI,
  remains explicitly unvalidated.
- Files and modules changed:
  - Worker `detectors/wanted.py`, `wanted_fixtures.py`, `wanted_replay.py`;
    existing SDK, sampler, analyzer registry/input selection and `owm` CLI.
  - Shared profile/evidence schemas, version readers, generated TS/Pydantic and
    vendored schemas, cross-runtime success/failure fixtures.
  - `profiles/generic-wanted/`, original versioned `fixtures/manifests/wanted-v1.json`,
    detector/runtime/fixture/profile/contract guides, README and milestone ledger.
  - Estimator/temporal unit tests, mixed-sampler runtime failure/cache/cancel tests,
    real FFmpeg import/proxy/calibration/API/replay/CLI/source-preservation tests.
- Public contracts or migrations:
  - Contracts **1.11**, additive: optional bounded `DetectorSettings.wanted`
    (`max_level`, `shape`, `max_missing_frames`, `debounce_ms`) and optional
    `RegionTemplateEvidence.frame_ms` in source coordinates. Prior 1.x fixtures
    remain readable. No migration or new API route/dependency.
  - SDK **1.1.0** adds immutable optional `Frame.region`; `None` retains the
    existing whole-frame convention. Producer `wanted-indicators` **1.0.0**;
    ROI sampler **gray-roi200x40-2fps-v1**.
  - Event type `openworld.wanted_level_changed`; scalar `from`, `to`, `max_level`,
    `direction`, `confirmed_at_ms`, `compatibility`. Region score/time plus asset
    identity and input provenance reference a locally reconstructable crop.
    Events contain no image bytes or filesystem paths.
  - Existing analyze API/CLI accepts profile `generic-wanted`. New
    `owm wanted replay <asset> --library <dir> --output <new-dir> [--crops]`
    and `owm wanted benchmark [--seconds 3600] [--repeats 5]`.
- Commands run:
  - `pnpm contracts:generate`, `pnpm format`, `OWM_REQUIRE_FFMPEG=1 pnpm check`.
  - `pnpm build` (production desktop, no installer).
  - Worker `mypy --platform win32`, `--platform linux`, normal darwin typecheck.
  - Focused `pytest tests/detectors tests/media/test_wanted.py tests/media/test_detectors.py`
    and final runtime/estimator tests.
  - `pytest tests/media/test_wanted.py::test_calibrated_hud_scale_replay_crops_and_api`
    with an isolated scratch root; manually inspected real replay trace/report.
  - `owm wanted benchmark --seconds 3600 --repeats 5`; source/FFmpeg tool versions
    recorded with the output.
- Test and validation results:
  - Full `OWM_REQUIRE_FFMPEG=1 pnpm check` passes: formatting, ESLint/Clippy/Ruff,
    REUSE, TypeScript/mypy, all tests and deterministic generated-contract drift.
  - Worker **736 passed, 1 skipped** (existing Windows-only junction case on macOS);
    Python contracts **161 passed**; TypeScript contracts **170 passed**; desktop
    **130 passed**; Rust **47 passed**. No M16-required automated case was skipped.
  - Worker mypy passes for darwin, win32 and linux. Production desktop build passes
    locally on macOS arm64, without installer; existing Vite >500 kB chunk warning.
    Hosted Windows/Linux CI is a separate check on the PR.
  - Estimation covers both shapes, maximum 1/3/5/10, every level and brightness
    0.55/0.8/1 (138 combinations), plus boundaries and hostile samples/ROIs.
  - Temporal cases cover exact transitions, sustained zero, flicker, brief and
    sustained occlusion, low confidence, gaps, cooldown flips/recovery and cancel.
  - Real H.264 fixtures at 720p CRF18, 1080p CRF32/70% brightness and 4K CRF38
    each produce exactly 0→2→5→0; source SHA-256 and mtime remain unchanged.
    A relocated 75%-scale HUD works after saved calibration. Unrelated compressed
    moving imagery is unknown throughout and emits no changes.
  - Trace review: 24 samples, three transitions first supported at 3000/6000/9000
    ms and confirmed at 4000/7000/10000 ms, three separate local PGM crops,
    confidence 0.977–0.989. Reports have no private paths or embedded pixels.
  - Local Apple M4/macOS arm64/Python 3.12.14: one hour (7200 samples), 900 events,
    five runs, median **5.599 s** (5.594–6.919), **642.9× real time**. Meets the
    2× processing budget on this reference machine; excludes proxy/decode/I/O,
    minimum Windows CPU and actual gameplay performance.
  - CI follow-up: Linux and Windows initially failed the 4K fixture before detector
    execution. Expanded diagnostics exposed M08's black-frame validation: Linux
    source/proxy luma 25.1/23.3 straddled cutoff 24 at 6000 ms. Set only the fixture
    canvas outside the ROI to brightness-scaled 64 and assert a >10-level raw
    luma margin. The dark ROI (20), compression cases, expected transitions and
    production proxy/detector thresholds remain unchanged. Persist proxy failure
    details in integration-test diagnostics; record background values in the manifest.
- Decisions made:
  - **Small prerequisite repair:** M14's 64×36 whole-frame sampler discarded
    individual HUD detail. Add fixed trusted-built-in ROI sampling (200×40 at
    2 fps), explicit crop metadata and per-ROI frame reuse within the existing
    runtime. Whole-frame behavior remains available; sampler provenance/cache
    differ and the M08 proxy-detail guard rejects undersized crops.
  - Independent original mathematical fixture polygons; no official templates.
    Bright rim/contrast, core fill and silhouette Dice establish slot state;
    minimum slot/support confidence is conservative and explainable, not a
    calibrated probability. All scores/settings are documented in the guide.
  - Visible inactive outlines establish zero. Missing or ambiguous HUD is unknown;
    sustained unknown loses the baseline. Initial state is a baseline, so no
    unseen transition is invented. State resets independently for each asset.
  - Replay never saves events. Optional crops are a separate explicit local media
    export. Existing output directories are refused; report is written last.
- Known limitations:
  - Regular horizontal high-contrast rows with uniform spacing and documented
    analytic geometry only. No claim for arbitrary HUDs, animation, colored-only
    fill, vanished zero outlines, police/chase semantics or actual GTA detection.
  - 2 fps coarse timing can miss brief states; no cross-clip inferred transitions.
    Proxy downscaling can discard small HUDs. Existing 64 MiB decoded-output cap
    (about 70 minutes of ROI samples) and 600-second tool timeout apply.
  - No lawful gameplay capture was supplied/selected, so the conditional local
    gameplay smoke test was not performed. No user libraries were searched.
  - M15 single-frame SDK preview still supports the bright-region example only;
    use the CLI for temporal wanted replay. No new UI/screenshots required.
  - Physical Windows testing, packaged/native app qualification and gameplay
    precision/recall remain separate. Existing M10 real-phone Windows smoke is pending.
- Follow-up milestones affected:
  - M17 is next (already Ready after M15). M18 and M21 are independently Ready.
    M19 still depends on M17/M18 and owns review, corrections and evaluation.
  - M29 bundles/discovers the shipped profiles and runtime; M30/platform/release
    milestones qualify dependencies, resource limits and distribution.
- Screenshots, reports, or artifacts:
  - [Wanted detector guide](../detectors/wanted.md): algorithm, settings, confidence,
    explicit synthetic case table, benchmark, crop/trace format, lawful evaluation.
  - [Fixture manifest](../../fixtures/manifests/wanted-v1.json) and executable tests
    reproduce the cases. Scratch replay/benchmark outputs remain outside Git.
  - No media, crops, models, databases, secrets, private user paths or build outputs
    are included in this PR. No visual product change.
