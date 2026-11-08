# Game profiles

Detector and HUD-region profiles, introduced by **M14 — Detector SDK and profile
schema**.

- `generic-open-world/` — synthetic temporal example (M14), not gameplay detection.
- `generic-wanted/` — M16 analytic star/disc row, synthetic validation only;
  [settings, replay and limits](./generic-wanted/README.md).
- `generic-text/` — M17 local region OCR and English synthetic vocabulary;
  [configuration and limits](./generic-text/README.md).
- `generic-audio/` — M18 supporting audio features (loudness onsets/impacts,
  silence, speech-like activity); [definitions and limits](./generic-audio/README.md).
- `gta-v/` — unvalidated placeholder; no game-specific manifest or templates bundled.
- `open-world-vi/` — first target profile; stays unvalidated until measured on
  legitimately obtained post-release footage.

Profiles must not contain official game assets (logos, fonts, textures, UI
images). Store regions, thresholds, and synthetic references only.
Profile data is licensed under Apache-2.0.

Profiles are local JSON data: `<catalog>/<id>/profile.json`. They never name executable plugins.
See [loading and inheritance](../docs/architecture/detectors.md).

## Vertical framing inputs (M25)

`safe_zones.preserve` names regions that vertical framing must protect. Optional
`subject_hints` names static subject regions in the same `regions` map. Both must
reference defined normalized rectangles; neither describes tracked objects.
M25 consumes effective local ROI calibration and checks upright frame compatibility.
See [vertical layouts](../docs/architecture/vertical-layouts.md) for conservative
fit fallbacks, confidence labels and editable suggestions.
