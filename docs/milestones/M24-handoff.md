## Milestone handoff

- Milestone: M24 — Render engine
- Outcome: A saved editor project revision becomes a validated horizontal H.264/AAC
  MP4 inside the library.
  - The FFmpeg graph is compiled from validated data into an argument array, with no
    shell.
  - Originals are verified by full SHA-256 and only read.
  - Trims are exact, so every golden output matches its target to the millisecond
    (budget ±100 ms).
  - Crop/fit/fill, privacy blur, gain/mute ranges and HDR tone mapping are rendered.
  - Hardware encoders are offered only after a real test encode, and a hardware
    failure offers an explicit CPU fallback.
  - Progress, cancellation, a free-space preflight, FFprobe/decode/black-frame
    validation and atomic completion with a reproducibility manifest are in place.
  - The editor has an Export panel.
  - Text overlays and caption burn-in are an explicit-omission hook, not drawn.
- Files and modules changed:
  - **Worker:** `render/plan.py` (IR and compiler), `encoders.py` (registry, quality
    mapping, probe), `presets.py`, `validate.py`, `service.py`; the `render` job
    handler, five API routes, worker startup (shared `Renderer`, staging cleanup);
    migration `0015_render_records.sql` and data fixture `data_v0015.sql`.
  - **Presets:** `presets/render/*.json` (three horizontal presets) and their README;
    REUSE licenses preset data as Apache-2.0.
  - **Contracts:** 1.18 `render` and `render-encoders` schemas, generated TS/Pydantic,
    semantic rules in both runtimes, valid/invalid fixtures.
  - **Desktop:** `ExportPanel.tsx` in the editor; the render API client and job
    wiring; five host-allowlisted routes. An M21 Rust refusal and an M22 UI assertion
    that encoded "no render yet" were updated.
  - **Docs:** `docs/architecture/render.md`, plus updates to the editor-projects,
    captions-and-audio, desktop-ui, storage, architecture index, contracts
    changelog/versioning, README and ledger.
  - **Tests:** `tests/render/test_plan.py`, `tests/media/test_render.py`,
    `ExportPanel.test.tsx`, plus updates to the editor and Rust tests.
- Public contracts or migrations:
  - **Contracts 1.18**, additive:
    - `render` (`RenderRecord`, `RenderPlan` IR plan_version 1, `RenderValidation`,
      library-relative `RenderOutput`, `RenderRequest`);
    - `render-encoders`.
  - **Migration 0015:** `render_jobs` gains project revision, encoder, plan,
    validation, output, fallback and finish time. The record ID is the job ID.
  - **API:**
    - `GET /v1/render/presets`
    - `GET /v1/render/encoders`
    - `POST /v1/projects/{id}/render` → a `render` job (state `rendering`)
    - `GET /v1/projects/{id}/renders`
    - `GET /v1/renders/{job}`
  - **Files:** outputs are written to `<library>/renders/<project>/<job>.mp4` with a
    `.manifest.json`; staging is `<library>/staging/renders/<job>/`.
- Commands run:
  - `pnpm contracts:generate`, `pnpm format`.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - Worker `mypy --platform darwin|win32|linux`.
  - `pnpm build`.
  - A golden measurement script, and a smoke render with the probe.
- Test and validation results:
  - **Full gate** (`OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`): formatting,
    ESLint/Clippy/Ruff, REUSE, TypeScript and mypy, all tests, and the contract drift
    check pass.
    - Worker: **961 passed, 1 skipped** (the existing Windows-only junction case on
      macOS).
    - Python contracts **259**, TypeScript contracts **280**, desktop **200**, Rust
      **48**.
    - The first run caught one unsorted import in the contracts package; it was
      fixed and the full gate re-run.
  - **Other checks:** mypy passes for darwin, win32 and linux, and the production
    macOS arm64 build passes.
  - **Unit tests** (19):
    - no user text or paths reach the argv; one `file:` element per path;
    - exact drift-free frame and sample counts; source-fps presets;
    - crop keyframe pieces; fill/fit; safe-mode note;
    - blur clamped to the frame;
    - gain/mute order and mute dominance;
    - video-only and generated-silence audio;
    - text refused or explicitly omitted; HDR LUT tone map;
    - limits, the graph-option choice by FFmpeg version, the Windows argv cap;
    - encoder argument mapping, a probe that requires real test encodes (cached);
    - fallback and disk-full mapping, the size estimate;
    - preset catalog validation.
  - **Real FFmpeg tests** (12):
    - goldens: single segment 4000/4000 ms; multi-segment with a silent clip, crop
      keyframes and blur 5500/5500 ms; mute/gain 6000/6000 ms (muted below −80 dB,
      gains ±1 dB); Unicode path with no audio 3000/3000 ms;
    - the FFprobe audit (H.264 High 1280×720, AAC 48 kHz stereo, only brand/encoder
      tags), a manifest validated with no paths, and unchanged source hash and mtime;
    - cancellation leaves no output and no staging, and the record says cancelled;
    - a hardware failure gives a failed record with a CPU fallback, and the separate
      CPU render succeeds;
    - unavailable hardware is refused up front;
    - disk full is refused at the preflight;
    - validation rejects empty, truncated, wrong-duration and black-over-bright
      outputs, and accepts black-over-black;
    - a changed source and text without `omit_text` are refused;
    - the job and API surface work;
    - a real VideoToolbox render passes validation on Apple M4.
  - **Desktop:** the Export panel covers flush-then-render, encoder availability and
    quality notes, explicit text omission, a validated result with its library path,
    the CPU fallback after a hardware failure, failed-check listing, refresh on job
    completion, and refused requests. The Rust allowlist accepts exactly the five
    routes and refuses query, ID and method variants.
- Decisions made:
  - **Input:** render from originals, not proxies, for quality. They are verified by
    full SHA-256 against the project identity, and size/mtime are re-checked before
    completion.
  - **Exact durations:** each piece (segment, split at crop keyframes) is cut to an
    exact frame and sample count derived from cumulative timeline positions, so error
    is at most half a frame and never accumulates. Silent clips get generated
    silence; an all-silent project is rendered video-only.
  - **Graph:** read from a file (`-/filter_complex` on FFmpeg ≥7,
    `-filter_complex_script` on 6), because FFmpeg 8 removed the latter and Windows
    limits command-line length. Limits: 120 pieces, 100 blurs, 500 audio ranges.
  - **Layouts:** `safe` renders as `fit` with a visible note, since HUD-aware layouts
    are M25. Blur regions are output-normalized, at least 8 px, and always rendered.
  - **Text:** `drawtext`/libass is missing from common FFmpeg builds (including
    Homebrew's), so text overlays and caption burn-in are refused unless the request
    sets `omit_text`. The plan then records `omitted`, and the UI requires an
    explicit checkbox.
  - **Hardware:** offered only after a real 0.5 s test encode. Each hardware encoder
    has a documented CRF mapping and a quality note. A failure is
    `render.hardware_encoder_failed` with `fallback: libx264`; nothing retries
    silently.
  - **Validation:** duration within ±100 ms; exactly the expected streams, codec,
    size, yuv420p and fps; no rotation metadata; only container brand/encoder tags;
    decodes at start, middle and end; black samples (luma < 20) flagged when the
    source is not dark (luma ≥ 40).
  - **Free-space preflight:** a conservative estimate plus a 64 MiB reserve; stderr
    and errno 28 also map to disk full.
- Known limitations:
  - **Text:** not drawn yet (explicit-omission hook). Vertical, HUD-aware and
    Discord-size presets, OTIO and sidecar export, HDR-preserving output and
    publishing are out of scope.
  - **Hardware coverage:** only CPU and Apple VideoToolbox were rendered for real
    (M4). NVENC, QSV and AMF are covered by argument and probe tests and a simulated
    hardware failure, not by GPUs.
  - **Getting the file out:** renders stay in the library. Saving a copy elsewhere or
    revealing the folder from the app belongs to M27.
  - **Complexity:** limited to 120 pieces per render.
  - **Fixture typo:** the existing `data_v0014.sql` header comment says "version 13"
    (pre-existing). Fixtures are immutable once a later migration exists, so it was
    left unchanged.
  - **Still outstanding:** M10's real-phone Windows smoke test, unvalidated GTA
    profiles and unmeasured real whisper.cpp recognition.
- Follow-up milestones affected:
  - **Now Ready:**
    - M25 (vertical/HUD-aware layouts), which builds on the IR's crop pieces and
      `safe` mode;
    - M27 (open exports), which adds save-elsewhere, sidecars and OTIO from the plan
      and manifest;
    - M29 (Windows packaging), which must bundle a known FFmpeg and qualify the
      encoders.
  - **Already Ready:** M26 and M28. M28's privacy blur regions already render through
    M24.
- Screenshots, reports, or artifacts:
  - [Render engine](../architecture/render.md) (IR, presets, hardware probes,
    validation thresholds, tool versions, golden outputs) and the
    [preset catalog](../../presets/README.md).
  - No secrets, user libraries, private paths, footage, generated media, models,
    databases or build outputs are included.
