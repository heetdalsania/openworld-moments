## Milestone handoff

- Milestone: M20 — Story engine
- Outcome: `owm-story` 1.0.0 generates deterministic, inspectable story candidates
  from current effective M19 events, supporting audio and source-timed transcript
  boundaries. Candidates expose exact source-event revisions/ranges, unique-time
  source ranges, setup/incident/escalation/payoff/reaction beats, alternative cuts,
  score components, coverage and warnings. Explicit accept/reject/restore decisions
  survive regeneration. Acceptance alone creates the existing Project/Story EDL;
  no rendering, publishing, model call or editing UI is introduced.
- Files and modules changed:
  - Worker `stories/algorithm.py`, `service.py`, `cli.py`, `golden.py`; CLI dispatch,
    story job handler, API routes and session attached-data guards.
  - Migration `0013_story_candidates.sql` and per-version upgrade fixture.
  - Contracts 1.15: two schemas, generated TS/Pydantic, dual-runtime semantic
    validation, shared success/hostile fixtures and job kind.
  - Rust host's explicit story route allowlist; existing job center's story label.
  - Algorithm, persistence/cancellation, media/API and migration tests; architecture,
    CLI, synthetic fixture/report, contracts, README and ledger documentation.
- Public contracts or migrations:
  - **Contracts 1.15**, additive: `story-candidate`, `story-candidates` and `story`
    job kind. Previous 1.x documents remain readable.
  - **Migration 0013:** immutable `story_candidates`, append-only
    `story_decisions`, `story_generations` cache markers, jobs table rebuilt to
    admit the new kind while preserving existing rows/constraints/indexes.
  - API: `GET|POST /v1/sessions/{id}/stories` and
    `POST /v1/sessions/{id}/stories/{candidateId}/decision`.
  - CLI: `owm story`, `owm story-review`, `owm story-golden`.
  - Accepted candidates use the existing Project/Story model; original source
    media and prior accepted/edited projects are never regenerated in place.
- Commands run:
  - Read README, full build specification and M20 brief; inspect M12/M19 handoffs
    and current code. M12 PR [#18](https://github.com/heetdalsania/openworld-moments/pull/18)
    and M19 PR [#25](https://github.com/heetdalsania/openworld-moments/pull/25) are
    merged ancestors of base `ba98e6365aadbaf4093288ec4c1a5d9458ea82f9`.
  - `pnpm contracts:generate`, `pnpm format`.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - Worker `mypy --platform win32` and `mypy --platform linux`.
  - `pnpm build` (production macOS arm64 development artifact, no installer).
  - Focused `pytest tests/stories tests/media/test_stories.py tests/storage/test_migrations.py`.
  - Python/TS contract tests, `owm story-golden`, and published-report comparison.
- Test and validation results:
  - Full local gate passes: formatting, ESLint/Clippy/Ruff, REUSE, TypeScript,
    mypy, all tests and generated-contract drift.
    - Worker **908 passed, 1 skipped**; the skip is the pre-existing Windows-only
      junction case on macOS. No M20-required case is skipped.
    - Python contracts **224**, TS contracts **242**, desktop **147**, Rust **47**.
  - Focused algorithm/service/media/migration suite: **51 passed**.
  - mypy passes for macOS, Windows and Linux. Production macOS arm64 build passes.
  - Golden metadata timelines: **10/10** declared windows/coverage pass, including
    every required case (isolated, chase, overlap, no payoff, long silence, duration
    pressure), plus sentence completion, empty input, supporting-audio-only and
    duplicate removal. All report zero duplicate time; supported sentence completion
    is retained. Duration pressure explicitly reports **zero setup coverage**.
  - Additional tests cover threshold boundaries, reviewed/model/audio policies,
    causal joins versus unrelated events, four preset maxima, insufficient footage,
    impossible speech bounds, score penalties/alternatives, output budgets,
    deterministic generation, version/review/transcript/layout invalidation,
    source-word remapping across hidden overlap and clip boundaries, audit history,
    explicit acceptance, edited/manual project preservation, pagination, cancellation
    before/during insert, transactional rollback, failures and concurrent input edits.
  - Real integration: generated FFmpeg media → detector → event correction →
    authenticated durable story job → exact revision/range inspection → acceptance
    into Project → rejection/force rerun with preserved decisions. Idempotent job
    submission, invalid/foreign requests and safe errors are checked. Original hash
    and mtime are unchanged.
  - Published sample matches a fresh report (identical Markdown and JSON document;
    committed JSON is indented). No footage, transcript text or private paths occur
    in the report. Median human boundary adjustment remains explicitly unmeasured.
- Decisions made:
  - Current reviewed events or unreviewed detector confidence ≥0.90 may seed;
    `--reviewed-only` disables the latter. Rejected/stale/superseded/legacy events
    and unreviewed model suggestions do not seed. Audio remains supporting-only,
    including after relabeling.
  - Use deterministic pre/post-roll, conservative type/temporal merges and fixed
    preset maxima. No missing event, payoff, reaction or footage is invented.
    Context and post-event speech/audio beats state their evidence basis.
  - Rebase transcript source coordinates into the current unique layout. Do not
    rely on stale saved session offsets or invoke speech recognition implicitly.
  - Bind all inputs/settings/version in the cache key, check again at atomic
    commit, and retain previous results on cancellation/failure/conflict.
  - Immutable candidate IDs are opaque content hashes in the existing ID shape;
    their suffix is not a creation timestamp. Decisions are separate revisions.
  - Identical regeneration preserves rejected/accepted decisions. Changed evidence
    or generator versions create fresh suggestions requiring new review; historical
    decisions never transfer automatically. Edited projects reject candidate-level
    state changes and remain owned by the downstream editor.
  - Story generation/review is available through CLI/API in M20. Visual editing
    and independent manual editor workflows remain M21/M22; compilation is a
    user-defined downstream workflow.
- Known limitations:
  - Synthetic metadata validates algorithm behavior, not semantic story quality,
    gameplay compatibility or publishing performance. GTA profiles stay Unvalidated.
  - Wanted/mission temporal proximity is a declared heuristic, not causal proof.
    Setup is measured pre-event context; a quiet visual joke/payoff may be unknown.
  - Duration pressure can omit early seeds, with explicit references and penalties.
    Long internal silence is penalized; the engine does not invent internal jump cuts.
  - Speech punctuation/pause grouping and scene hints are best effort. No scene
    detector or multilingual language model is added. Unsupported long utterances
    are visibly marked truncated when a hard maximum prevents preservation.
  - M18 real whisper.cpp recognition remains unqualified; only existing local timing
    evidence is consumed. No engine/model is required or downloaded by M20.
  - Bounds: 1,000 members/candidates, 5,000 events, 10,000 transcript rows,
    50,000 words and 50,000 candidate event references. Oversized input fails closed.
  - M10's real-phone Windows smoke test remains pending; native/clean-machine
    release qualification and editor UX remain their assigned milestones.
- Follow-up milestones affected:
  - **M21 next:** keep manual creation independent; consume accepted Project EDLs
    and preserve exact asset/source ranges, candidate provenance and edited ownership.
  - **M22:** story/candidate cards, beat/score inspection and focused editing UI.
    List custom generations with their matching options and show stale history clearly.
  - M26 may index candidate/story metadata. M32 retains real gameplay/editor/release
    qualification; M20 does not satisfy those later gates.
- Screenshots, reports, or artifacts:
  - [Algorithm/presets/scoring/reconciliation](../architecture/stories.md),
    [CLI and coverage guide](../stories/README.md).
  - [Synthetic fixture](../../fixtures/manifests/story-golden-v1.json),
    [coverage Markdown](../stories/sample/report.md), [coverage JSON](../stories/sample/report.json).
  - No new UI editing surface; validation is metadata, API, CLI and production build.
    No secrets, user libraries, private paths, databases, models, footage or build
    outputs are committed.
