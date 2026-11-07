# Game profiles

Detector and HUD-region profiles, introduced by **M14 — Detector SDK and profile
schema**.

- `generic-open-world/` — synthetic temporal example (M14), not gameplay detection.
- `gta-v/` — reference profile for a released game, used for calibration.
- `open-world-vi/` — first target profile; stays unvalidated until measured on
  legitimately obtained post-release footage.

Profiles must not contain official game assets (logos, fonts, textures, UI
images). Store regions, thresholds, and synthetic references only.
Profile data is licensed under Apache-2.0.

Profiles are local JSON data: `<catalog>/<id>/profile.json`. They never name executable plugins.
See [loading and inheritance](../docs/architecture/detectors.md).
