# Generic audio features

Reference profile, version 1.0.0, Apache-2.0. It enables the built-in
`audio-features` detector, which needs only the `audio.pcm` capability and no
regions or locale pack.

Outputs are **supporting evidence only**: loudness onsets and impacts, silence, and
speech-like activity, each labelled `evidence_role: "supporting"`. They never claim
that a moment is important. Analysis reads the first audio stream of the checked
playback copy. Clips without audio complete with no events.

Run it through the existing analyze job/API/CLI, for example:

```bash
uv run --directory services/media-worker owm analyze ses_<ULID> --library /absolute/library --profile generic-audio
```

The broad frame list exists only because every profile declares one. Audio-only
detectors skip picture-geometry checks. Thresholds are fixed in the versioned
detector, not in this profile.

See [feature definitions, tolerances and limits](../../docs/detectors/audio.md).
Game compatibility is unvalidated; all quality evidence is synthetic.
