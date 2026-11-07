# Generic analytic wanted indicators

Synthetic-only reference profile, version 1.0.0, Apache-2.0. Game compatibility is
**unvalidated**, including GTA VI. No official art, font, footage or template is used.

The profile expects a regular horizontal row of five bright five-point stars,
filled from left to right with visible outlines in every inactive slot. Zero
requires all five outlines; an absent HUD means unknown. The default normalized
ROI is `[0.5, 0.05, 0.45, 0.16]` on a 16:9 picture, minimum 640×360. The M08 proxy
must preserve at least 12 pixels per slot and 12 pixels of height.

Use Settings → Calibrate detector profile regions to align the complete row,
including equal slot spacing and small surrounding margins. Save locally. M15's
single-frame detector preview supports only the bright-region example; use the
M16 replay CLI to inspect temporal wanted estimates. A calibration patch changes
coordinates only. To change count or shape, create a local JSON profile based on
this one; `wanted.max_level` permits 1–10 and `wanted.shape` permits `star`/`disc`.

Defaults: three supporting samples at 2 fps, one tolerated consecutive unknown,
1500 ms between emitted changes, minimum confidence 0.8. The first stable state
establishes a baseline without inventing a transition. Occlusion longer than the
allowance loses that baseline and requires reacquisition.

See [algorithm, replay, evidence and exact validation](../../docs/detectors/wanted.md).
