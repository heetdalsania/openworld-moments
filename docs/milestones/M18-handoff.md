## Milestone handoff

- Milestone: M18 — Audio analysis and transcription
- Outcome: The detector runtime now produces deterministic, time-aligned audio
  evidence: onsets and impacts, silence, and speech-like activity, read from the
  checked proxy's first audio stream. Every audio event is labelled supporting
  evidence, never a highlight. Sessions can optionally be transcribed on this
  computer by the user's own whisper.cpp with an explicitly installed model.
  - Nothing downloads and nothing is uploaded.
  - Word timings are mapped into M13 session time.
  - Each clip commits independently, so the job is cancellable and resumable.
  - The session screen shows a privacy notice and offers transcribe, rebuild and a
    text-only delete.
  - All quality evidence is synthetic, and no real speech engine runs in CI.
- Files and modules changed:
  - **Worker detectors:** `detectors/audio.py` (features and the `audio-features`
    built-in), `audio_input.py` (fixed FFmpeg graph, track policy),
    `audio_fixtures.py`, `audio_benchmark.py`; `sdk.py` (`AudioSamples`,
    `AnalysisContext.audio`); `service.py` (audio sampling and provenance,
    `checked_proxy` and `layout` helpers); `__main__.py` (CLI).
  - **Worker transcription:** `transcripts/` (`whisper.py` adapter and parser,
    `models.py` explicit model manager and catalog, `service.py` job, session-time
    mapping and deletion).
  - **Worker wiring:** `transcribe` handler, four API routes, worker startup
    (shared `Transcriber`, scratch cleanup), migration `0011_transcripts.sql` and its
    data fixture.
  - **Contracts:** 1.13 schemas (`transcript`, `transcription`, `speech-models`;
    audio evidence and the capability), generated TS/Pydantic, semantics in both
    runtimes, and valid/invalid fixtures.
  - **Profile:** `profiles/generic-audio/`.
  - **Desktop:** `TranscriptPanel.tsx` in the session view; transcription API client
    and job labels; host `DELETE` method and four allow-listed routes; styles.
  - **Docs:** `docs/detectors/audio.md`, `docs/architecture/transcription.md`,
    ADR-0006, `docs/guides/transcription.md`, the detector/storage/desktop/contract
    docs, README and ledger.
  - **Tests:** `tests/detectors/test_audio.py`, `tests/media/test_audio.py`,
    `tests/transcripts/` (parser, models, fake whisper.cpp and fixture),
    `tests/media/test_transcription.py`, `TranscriptPanel.test.tsx`, plus updates to
    the Rust allowlist tests.
- Public contracts or migrations:
  - **Contracts 1.13**, additive:
    - `AudioEvidence` gains optional `feature`, `level_dbfs` and `role`; `role` can
      only be `"supporting"`;
    - profile capability `audio.pcm`;
    - new `transcript`, `transcription` and `speech-models` contracts.

    Prior 1.x documents remain readable.
  - **SDK 1.3.0.** Producer `audio-features` 1.0.0 emits
    `openworld.audio_impact`, `openworld.audio_onset`, `openworld.silence` and
    `openworld.speech_activity`. Sampler `pcm8k-mono-speechband-v1`; provenance
    `audio_track`.
  - **Migration 0011:**
    - `transcript_segments` gains `asset_id`, source times, `transcriber_json` and
      `created_at`;
    - new `transcript_runs` table;
    - rows from before M18 are kept, but the API does not list them.
  - **API:**
    - `GET /v1/transcription/models`;
    - `POST /v1/sessions/{id}/transcribe` → a `transcribe` job (state
      `transcribing`);
    - `GET` and `DELETE /v1/sessions/{id}/transcript`.

    The host allow-lists exactly these routes and adds the `DELETE` method.
  - **CLI:** `owm audio benchmark`, `owm speech doctor`, and
    `owm models list|install|remove --library`.
- Commands run:
  - `pnpm contracts:generate`, `pnpm format`.
  - `OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`.
  - Worker `mypy --platform darwin|win32|linux`.
  - `pnpm build` (production macOS arm64 desktop, no installer).
  - `owm audio benchmark --minutes 10 --repeats 3`.
- Test and validation results:
  - **Full local gate** (`OWM_REQUIRE_FFMPEG=1 OWM_REQUIRE_OCR=1 pnpm check`):
    formatting, ESLint/Clippy/Ruff, REUSE, TypeScript and mypy, and all tests pass.
    - Worker: **867 passed, 1 skipped**. The skip is the existing Windows-only
      junction case on macOS.
    - Python contracts **194**, TypeScript contracts **206**, desktop **138**, Rust
      **47** (26 unit plus integration suites).
    - The contract drift check passes with the generated output staged. It flags
      unstaged generated files by design.
    - No M18-required case is skipped.
  - **mypy:** passes for darwin, win32 and linux.
  - **Build:** the production desktop build passes on macOS arm64 (no installer).
  - **Synthetic audio** (unit, PCM):
    - steady tones and hum produce no events;
    - digital silence is one confidence-1 interval;
    - impacts fall within ±20 ms at four positions, and two impacts 400 ms apart
      stay separate;
    - a sustained onset is not classed as an impact;
    - speech-like boundaries fall within ±150 ms at about 4 Hz syllables;
    - tone, hum and loud steady noise are rejected as speech;
    - no-audio, empty and sub-hop clips complete;
    - output is contract-valid and deterministic, and cancellation stops it.
  - **Real path** (generated clips → AAC proxy → analysis):
    - impact at 5250 ms within ±30 ms (measured ≤10 ms);
    - speech 1000–4000 ms within ±150 ms;
    - the three expected silence intervals;
    - a silent clip yields silence only, and a clip without audio completes with no
      events;
    - a two-track clip analyzes the first stream (`first-of-2`);
    - FFmpeg cancellation, cache reuse, and unchanged source hash and mtime.
  - **Transcription** (FFmpeg plus a whisper.cpp test double; the 16 kHz mono WAV is
    checked):
    - the word-time fixture gives exact words, times and confidences;
    - two clips land in session time (0/2500/6000/8500 ms);
    - provenance is recorded; the cache serves reruns without calling the engine;
      force and language changes are new keys; results replace rather than append;
    - cancelling a hung engine kills its process (the heartbeat stops), empties
      scratch, and the next run resumes (`cached`, then `computed`);
    - engine failure and garbage output fail safely without transcript text, and the
      job reports a partial failure;
    - a clip without audio is skipped;
    - a missing model or engine is refused (422 or status reason) with no engine
      call;
    - a changed model is refused;
    - deletion removes text only, keeping media, the proxy and events, and a rebuild
      recomputes;
    - the API (auth, 201/422/404, job ready, GET/DELETE) and CLI (install, list,
      remove, doctor) work.
  - **Desktop:** the Transcript panel covers the notice, missing engine and model
    guidance, transcribe and rebuild options, seeking from a line, two-step delete,
    progress and failure refresh, and a refused request. The Rust allowlist accepts
    exactly the four routes and refuses variants with queries, bad IDs or other
    methods.
  - **Benchmark:** Apple M4 / macOS arm64 / Python 3.12.14, 10 synthetic minutes ×3:
    0.159 / 0.156 / 0.156 s. That is a median **0.156 s**, about **3,850× real
    time**, for feature extraction only (excluding decode, proxy and I/O).
- Decisions made:
  - **Audio source:** analysis audio comes from the checked proxy (never the
    original), using its first audio stream, the same as the waveform and
    fingerprints. Provenance names the stream (`first-of-N` or `none`). A clip
    without audio completes with no events. Other tracks are future work.
  - **Fixed feature definitions** in the versioned detector, with no profile
    thresholds and nothing from a profile reaching FFmpeg:
    - 10 ms hops, 100 ms envelope blocks;
    - onset: a rise of at least 15 dB to at least −40 dBFS; impact: a decay of at
      least 12 dB within 300 ms;
    - silence: below −50 dBFS for at least 1 s;
    - speech-like activity: at least 45% of energy in the speech band, at least
      3 dB of modulation, and 1.5–10 syllable peaks per second.
  - **Confidence:** heuristic, capped at 0.9 for onsets and speech.
  - **No loudness events:** the envelope is not emitted as events, so "loud" is
    never presented as a moment.
  - **Engine:** the whisper.cpp CLI as an optional subprocess (`-ojf` full JSON),
    not Python bindings, for isolation, killable cancellation and no new
    dependency.
  - **Models:** installed only from a local file, with magic, size and SHA-256
    checks, a declared license, and re-hashing before and after each clip. The
    catalog is informational and links to sources for manual download.
  - **Transcripts:**
    - segments and words keep source times and M13 session times;
    - speech inside hidden repeated footage is dropped;
    - no speaker field (diarization is out of scope);
    - FTS-ready rows, with the FTS5 index left to M26;
    - deletion removes only derived text and run rows.
  - **Privacy:** errors never contain transcript text or paths. Scratch WAVs live
    in `<library>/staging/transcripts`, removed per clip, on cancel, and at worker
    start.
- Known limitations:
  - **No real engine in CI.** CI uses a whisper.cpp test double that mirrors the
    documented CLI and JSON. Real recognition quality, token-timing accuracy
    (typically within a few hundred ms without DTW) and engine speed are
    unmeasured here. The adapter has not been run against a real whisper.cpp
    build in this repository.
  - **Audio not validated on gameplay:** music with a syllable-like rhythm can read
    as speech-like activity. Laughter detection and multi-track analysis are not
    implemented.
  - **Clip length:** audio decode is capped at about 35 minutes per clip
    (64 MiB). Longer clips fail that unit only.
  - **Snapshots:** transcripts and events do not follow later session corrections;
    re-run them.
  - **No model UI:** model management is CLI-only. A model manager with downloads,
    updates and rollback (spec 10.7) is M29/M34.
  - **M10:** its real-phone Windows smoke test remains pending.
- Follow-up milestones affected:
  - **Now Ready:** M19 (event review) has all dependencies. It consumes audio
    evidence (supporting only) and transcript segments.
  - **Later consumers:** M23 (captions/audio) and M28 (privacy review) use
    transcripts once M22 lands. M26 adds the FTS5 index over `transcript_segments`.
  - **Packaging:** M29/M34 bundle or qualify whisper.cpp and add a model manager UI.
  - **Still Ready:** M21.
- Screenshots, reports, or artifacts:
  - [Audio features](../detectors/audio.md), [transcription](../architecture/transcription.md),
    [ADR-0006](../architecture/adr/0006-local-transcription.md),
    [user guide](../guides/transcription.md).
  - The benchmark is reproducible with `owm audio benchmark`.
  - No secrets, user libraries, private paths, footage, models, databases, build
    outputs or generated media are included.
