# Detector documentation

M14's [runtime guide](../architecture/detectors.md) documents the built-in SDK,
profile format, cache, provenance, failure model and example CLI.

To add a built-in detector:

1. Implement `Detector` from `openworld_moments.detectors.sdk` using only the
   immutable context. Keep work bounded and check cancellation between samples.
2. Register its factory explicitly in `detectors.service.BUILTINS`. Profiles cannot
   load code. Bump the detector version whenever behavior changes.
3. Declare required regions/capabilities and a local licensed profile/locale pack.
4. Yield source-time `Detection` records with confidence and explainable evidence.
5. Add lawful synthetic success, failure, ambiguity, boundary and cancellation
   cases, plus processing measurements. Do not commit game assets or footage.
6. Document limitations and exact validation status. GTA profiles stay unvalidated
   until measured on legitimate post-release captures.

`synthetic-bright-region` demonstrates consecutive-frame confirmation; isolated
bright frames do not emit observations. Run it with
`uv run --directory services/media-worker owm demo` from the repository root.

M16's [wanted detector guide](./wanted.md) documents the shipped analytic estimator,
confirmation/debounce settings, synthetic case table, local replay and benchmark.
`generic-wanted` uses the saved calibration overrides and the same analyze API.

M17's [text detector guide](./text.md) covers local Tesseract, locale packs,
region preprocessing, appearance/disappearance intervals, line evidence, missing
OCR behavior and real-engine synthetic tests. [ADR-0005](../architecture/adr/0005-local-ocr.md)
records the dependency, model and packaging decisions.

M18's [audio feature guide](./audio.md) defines the deterministic loudness envelope,
onset/impact, silence and speech-like activity features, their timing tolerance,
the first-stream track policy and no-audio behavior. Audio events are always
**supporting evidence**, never highlights. Optional local transcription is covered by
[transcription](../architecture/transcription.md).

Event review and reproducible precision/recall evaluation are available in M19.

## Calibrating an installed profile

Use Settings → Calibrate detector profile regions to select an imported frame,
adjust named regions, compare defaults and save local overrides. Export a
media-free JSON patch for coordinate review; a patch is not a complete profile
manifest and is imported through the calibration screen. Crop samples are a
separate explicit export. See [calibration](../architecture/profile-calibration.md)
for coordinates, keyboard controls, compatibility, schema, API and preview limits.

M19 supplies [event review](../architecture/event-review.md) and [local evaluation](../evaluation/README.md), including the [synthetic sample](../evaluation/sample/report.md).
