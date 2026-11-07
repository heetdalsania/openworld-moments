# Game profiles

Detector and HUD-region profiles, introduced by **M14 — Detector SDK and profile
schema**.

- `generic-open-world/` — synthetic temporal example (M14), not gameplay detection.
- `generic-wanted/` — M16 analytic star/disc row, synthetic validation only;
  [settings, replay and limits](./generic-wanted/README.md).
- `generic-text/` — M17 local region OCR and English synthetic vocabulary;
  [configuration and limits](./generic-text/README.md).
- `gta-v/` — unvalidated placeholder; no game-specific manifest or templates bundled.
- `open-world-vi/` — first target profile; stays unvalidated until measured on
  legitimately obtained post-release footage.

Profiles must not contain official game assets (logos, fonts, textures, UI
images). Store regions, thresholds, and synthetic references only.
Profile data is licensed under Apache-2.0.

Profiles are local JSON data: `<catalog>/<id>/profile.json`. They never name executable plugins.
See [loading and inheritance](../docs/architecture/detectors.md).
