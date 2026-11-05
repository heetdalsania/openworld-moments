# Game profiles

Detector and HUD-region profiles, introduced by **M14 — Detector SDK and profile
schema**.

- `generic-open-world/` — game-agnostic defaults.
- `gta-v/` — reference profile for a released game, used for calibration.
- `open-world-vi/` — first target profile; stays unvalidated until measured on
  legitimately obtained post-release footage.

Profiles must not contain official game assets (logos, fonts, textures, UI
images). Store regions, thresholds, and synthetic references only.
Profile data is licensed under Apache-2.0.
