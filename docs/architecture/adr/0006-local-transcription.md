# ADR-0006: Optional local transcription with whisper.cpp

- Status: Accepted for the M18 implementation; subject to maintainer review
- Date: 2026-11-07
- Milestone: M18

## Context

M18 needs optional word-timed transcripts for event review, captions, and story
boundaries. Several constraints apply:
- Cloud transcription and silent downloads are forbidden.
- Transcripts are private data.
- The worker already has a cancellable, output-capped process runner and the M17
  pattern for an optional local engine (ADR-0005).

## Decision

**Engine:** use the user's own **whisper.cpp CLI** (`whisper-cli`/`whisper-cpp`, or
`OWM_WHISPER`).
- It must support `--output-json-full`.
- It is invoked with a fixed argument array on an owned 16 kHz mono WAV. That WAV is
  extracted from the checked M08 proxy's first audio stream.
- The token offsets and probabilities in its JSON output are parsed under strict
  bounds.
- Its executable SHA-256 and best-effort version go into provenance and the cache
  key.

**Models are installed explicitly** from a local file (`owm models install`):
- the ggml magic and size are checked;
- the file is copied with a SHA-256 sidecar and the declared license;
- the hash is re-verified before and after each clip.

A static catalog names well-known models and their source page for manual
download. **Nothing is ever downloaded or uploaded.** A missing engine or model
refuses the request with a plain message; analysis and playback are unaffected.

**Results:**
- Each clip commits independently, so a run can be cancelled and resumed.
- Results are mapped into M13 session time, with speech inside hidden repeated
  footage dropped.
- Deleting removes derived text only.
- Transcript text never appears in errors or logs.

The deterministic audio features (`audio-features`) need no model. They are pure
Python over a fixed FFmpeg graph, and are labelled supporting evidence.

## Consequences

- **Optional:** transcription works only once the user installs whisper.cpp and a
  model.
- **CI:** CI uses a whisper.cpp test double, not a real engine, so recognition
  quality, real timing accuracy and speed are unmeasured here.
- **Timing:** without DTW, whisper.cpp token times are coarse (typically within a few
  hundred ms). The app preserves them exactly but cannot improve them.
- **Licenses:** whisper.cpp and the official ggml Whisper weights are MIT. User-
  declared licenses are recorded, not verified.
- **Packaging:** bundling the engine, a download UI and architecture qualification
  are M29/M34. No Python dependency is added.

## Alternatives considered

- **Python bindings (pywhispercpp, faster-whisper):** native wheels, a larger
  dependency and packaging surface, and weaker isolation and cancellation than a
  killable subprocess.
- **Bundling and auto-downloading a model:** violates "no silent download" and adds
  hundreds of megabytes to installs.
- **Cloud APIs:** out of scope and a privacy risk.

## References

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (MIT); CLI options include `-ojf`, `-of`, `-l`, `-t`, `-np`
- [ggml model files](https://huggingface.co/ggerganov/whisper.cpp)
