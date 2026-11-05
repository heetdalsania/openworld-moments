# M15 — Profile calibration UI

## Objective

Let users and detector contributors visually calibrate normalized regions of interest and export safe profile patches without editing YAML by hand.

## Dependencies

M09 and M14 merged.

## Required context

Read specification sections 8.4.5, 10.7, and 19.2.

## In scope

- Select representative frame from an imported asset.
- Draw, move, resize, name, and preview normalized ROIs.
- Apply profile region defaults and create local overrides.
- Test crop preprocessing and detector preview when available.
- Export/import profile patch with provenance and compatibility metadata.
- Reset and compare to base profile.

## Out of scope

- Training models, editing upstream profiles automatically, and full profile marketplace.

## Implementation steps

1. Build frame selector and coordinate transform library.
2. Build accessible ROI canvas with keyboard adjustments.
3. Persist local override separate from installed profile.
4. Add preprocessing preview and sample export.
5. Validate patch through M14 schema.
6. Add diff/reset UI and documentation.
7. Add interaction and round-trip tests.

## Acceptance criteria

- Normalized regions round-trip across 720p, 1080p, and 4K frames.
- Keyboard can move/resize a selected region precisely.
- Local overrides survive profile updates without mutating the installed profile.
- Invalid/out-of-bounds regions cannot be saved.
- Exported patch contains no source frame or gameplay content.
- Reset returns exactly to base profile values.

## Required validation

- Coordinate unit tests.
- UI interaction tests at several aspect ratios.
- Patch export/import/reset E2E test.

## Handoff

Provide screenshots, coordinate behavior, patch format, accessibility controls, and known canvas limitations. Update M15.

