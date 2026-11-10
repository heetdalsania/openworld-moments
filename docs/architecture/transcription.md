# Local transcription (M18)

Transcription is **optional and fully local**:
- **Engine:** the user's own [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
  executable.
- **Model:** a model file the user downloaded and installed explicitly.
- **Network:** audio and text are never uploaded. M29 adds explicit, optional model
  downloads in Settings; listing models never contacts the network.

Without an engine or model, everything else keeps working and transcription
explains what is missing.

Code: `services/media-worker/openworld_moments/transcripts/`:
- `whisper.py`: the adapter and output parser;
- `models.py`: installed models and the catalog;
- `service.py`: the job, session-time mapping, and deletion.

Decision record: [ADR-0006](./adr/0006-local-transcription.md).

## Installing (explicit, never automatic)

1. **Engine:** install whisper.cpp so `whisper-cli` (or `whisper-cpp`) is on `PATH`,
   or set `OWM_WHISPER` to the executable.
   - The build must support `--output-json-full` (`-ojf`).
   - Check it with `uv run --directory services/media-worker owm speech doctor`.
2. **Model:** download a ggml model yourself, then install it into the library:

   ```bash
   uv run --directory services/media-worker owm models install --library /absolute/library base.en /path/to/ggml-base.en.bin --license MIT
   ```

   The install step:
   - copies the file to `<library>/models/whisper/ggml-<name>.bin`;
   - checks the ggml magic bytes, a size of 1 KiB–4 GiB, and that it is a regular
     file (not a link);
   - records a sidecar with the name, size, SHA-256, declared license and install
     time.

   The original file is left untouched. `owm models list` and `owm models remove`
   manage installed models.
3. **Catalog:** `GET /v1/transcription/models` lists known models (tiny, base,
   small, medium; English-only and multilingual). For each it gives the approximate
   size, the MIT license, and the source page, so the user can fetch one by hand.
   Listing the catalog makes no network request.

**Licenses:**
- whisper.cpp and the official ggml conversions of OpenAI's Whisper weights are MIT.
- The license a user declares at install time is recorded, but it is not a legal
  check.
- No engine or model weights are committed or bundled. The M29 Windows model-manager
  candidate supports curated, signed-catalog downloads; see [Windows packaging](./windows-packaging.md).

## How a session is transcribed

`POST /v1/sessions/{id}/transcribe` with `{model, language?: "auto"|code, force?}`
creates a durable `transcribe` job. The state shown while running is `transcribing`.

**At submission**, the request is refused with 422 if:
- the model is not installed, or
- the engine is missing, or
- the language is not `auto` or a 2–3 letter code.

**Before running**, the job re-checks the model's SHA-256 against its sidecar. A
changed file fails with `transcription.model_changed`.

**For each clip**, in session order:

1. **No audio:** the outcome is `skipped` with `transcription.no_audio`.
2. **Checked proxy:** the same checked M08 proxy as detectors, reached through
   `Analyzer.checked_proxy`. The original is never read.
3. **Cache:** the key covers the transcriber version, engine SHA-256, model SHA-256,
   requested language, proxy input key, session layout, clip, and the first-stream
   policy. On a hit the outcome is `cached` and the engine does not run, unless
   `force` is set.
4. **Scratch audio:** FFmpeg writes the first audio stream as 16 kHz mono PCM WAV into
   an owned folder, `<library>/staging/transcripts/<job>-…/`.
5. **Engine run:** whisper.cpp runs with a fixed argument array:
   `-m model -f clip.wav -l <lang> -t <threads> -ojf -of clip -np`.
   - The timeout is the larger of 600 s and 6× the clip duration.
   - Paths are redacted from logs, and stdout is capped.
6. **Parsing:** the JSON output is parsed under strict bounds:
   - at most 32 MiB, 20,000 segments, 1,000 words per segment;
   - control characters and non-finite numbers are rejected;
   - text is limited to 2,000 characters per segment and 200 per word.
7. **Mapping and commit:** times are mapped into session time (below). The model
   hash is re-checked, and the session layout is re-checked inside the commit
   transaction. The clip's segments then replace its previous ones together with
   its run row.

**Outcomes:**
- Each clip has its own outcome: `computed`, `cached`, `skipped` or `failed`.
- A job with any failed clip ends `failed` with `transcription.partial_failure`
  **and** the detailed result. Completed clips stay committed.
- Error messages never contain transcript text, engine output or paths.

## Word timing and session time

- **Words:** whisper.cpp tokens are joined into words. A token starting with a space
  begins a new word. Special tokens (`[_BEG_]`, `[_TT_…]`, `<|…|>`) are skipped.
- **Times:**
  - a word spans its first token's start to its last token's end;
  - its confidence is the lowest token probability;
  - a segment's confidence is the mean of its words;
  - times are clamped into the clip and made monotonic.
- **Session time:** like events, transcripts use M13 unique session time:
  - speech entirely inside a clip's hidden repeated start is dropped, because it
    already plays in the previous clip;
  - a word crossing that boundary starts at the first unique moment;
  - every segment and word keeps `source_start_ms` and `source_end_ms`.

**Timing tolerance:**
- The app preserves the engine's token offsets exactly. This is tested with a
  whisper.cpp-format fixture.
- Their accuracy depends on whisper.cpp: without DTW alignment, token timestamps
  are typically within a few hundred milliseconds.
- Transcripts are snapshots: after a session correction, transcribe again.

## Storage

Migration **0011** extends `transcript_segments` with:
- `asset_id` (cascades with the asset);
- `source_start_ms` and `source_end_ms`;
- `transcriber_json` (engine, version, SHA-256, model, model SHA-256, transcriber
  version, requested language);
- `created_at`.

It also adds `transcript_runs (session_id, asset_id) → cache_key, language,
segment_count, computed_at`, cascading with the session and the asset.

**Rows from before M18:** they have no transcriber and are left untouched. The
transcript API lists only M18 rows.

**Search readiness:** segments are sentence-sized, have a stable integer row ID, and
keep `session_id`, `start_ms`, `text` and `language`. They are ready for the M26
FTS5 index, which is not created here.

A session with transcript rows counts as having attached data (#17): regrouping
keeps it, and merging it away is refused until the transcript is deleted.

## Privacy and deletion

- **Visible notice:** the Transcript panel on the session screen always shows a
  privacy notice. It says transcription is optional and local, that nothing is
  uploaded or downloaded, that transcripts can contain private conversations, and
  that they can be deleted without affecting videos.
- **Deletion:** `DELETE /v1/sessions/{id}/transcript` (and **Delete transcript…** with
  confirmation) removes the session's derived text and its run rows. Media files,
  proxies, events and other derived artifacts are untouched. Rebuilding afterwards
  recomputes rather than reusing the deleted results.
- **No leaks:** transcript text never appears in logs, job errors, or support data.
  Scratch WAVs are removed after each clip, after cancellation, and at worker start.

## Cancellation

- **Stopping:** cancelling the job kills FFmpeg or whisper.cpp through the runner,
  which kills and reaps the process, and removes the scratch folder.
- **Resuming:** clips that finished earlier stay cached, so running again resumes.
- **Test:** the cancellation test proves the engine process stopped (its heartbeat
  file no longer changes) and that staging is empty.

## API, UI and CLI

| Surface | What |
|---|---|
| `GET /v1/transcription/models` | `speech-models` contract: engine availability (with a plain reason), installed models, catalog |
| `POST /v1/sessions/{id}/transcribe` | `transcribe` job; result contract `transcription` |
| `GET /v1/sessions/{id}/transcript` | `transcript` contract, ordered by session time |
| `DELETE /v1/sessions/{id}/transcript` | `{deleted_segments}` |
| Desktop | Transcript panel: notice, engine/model guidance, model and language, Transcribe / Rebuild, two-step Delete, timed lines that seek the player. Host allow-list adds exactly these four routes |
| CLI | `owm speech doctor`, `owm models list|install|remove --library <dir>` |

## Validation

- **Parser and model manager** (`tests/transcripts/test_whisper.py`):
  - the word-time fixture, sub-word joining, clamping and monotonic times;
  - invalid and hostile output, unknown languages;
  - hidden-overlap mapping and engine probing;
  - model install validation, refusing links, ignoring tampered sidecars, and the
    catalog.
- **Real path** (`tests/media/test_transcription.py`), FFmpeg plus a whisper.cpp test
  double:
  - two clips in session time, provenance, the cache, force and language keys;
  - cancellation that kills the engine and resumes;
  - failures without text leakage, including a partial-failure job;
  - clips without audio, missing model or engine (nothing downloaded), and a changed
    model;
  - deletion that keeps media and events;
  - the job and API surface, and the CLI.
- **Not tested here:** no real whisper.cpp engine or model runs in CI. Recognition
  quality, real token-timing accuracy and engine performance are therefore
  unmeasured in this repository. The adapter targets the documented whisper.cpp
  JSON format.
