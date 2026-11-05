# M18 — Audio analysis and transcription

## Objective

Produce timestamped audio evidence and optional local word timings that support event review and story boundaries without treating loudness as proof of importance.

## Dependencies

M14 merged.

## Required context

Read specification sections 8.4.4 Audio peaks, 8.7.4, and 10.7.

## In scope

- Analysis-audio extraction.
- Loudness envelope, onset/impact peaks, silence, and speech activity.
- Optional whisper.cpp model manager integration interface.
- Word/segment transcript contracts with language/confidence.
- Resumable/cancellable jobs and caches.
- No-audio and multi-track handling policy.

## Out of scope

- Speaker diarization, emotion diagnosis, translation, dubbing, and cloud transcription.

## Implementation steps

1. Extract normalized analysis audio without modifying source.
2. Implement deterministic signal features and event evidence.
3. Integrate optional whisper.cpp invocation behind explicit model installation.
4. Map words to virtual session time.
5. Persist transcript and FTS-ready segments.
6. Add privacy notice and deletion/rebuild controls.
7. Benchmark CPU, cancellation, and model absence.

## Acceptance criteria

- Audio features are time-aligned within defined tolerance.
- Silence and no-audio files complete without failure.
- Transcription is fully optional and no model downloads silently.
- Cancelling stops model/FFmpeg subprocesses.
- Loudness events are labelled supporting evidence, not highlights.
- Transcript deletion removes derived text without deleting media.

## Required validation

- Synthetic tone, impact, silence, speech, no-audio, and multi-track tests.
- Transcript word-time fixture test.
- Missing-model and cancellation tests.

## Handoff

Document feature definitions, model installation, licenses, timing tolerance, caches, and privacy controls. Update M18.

