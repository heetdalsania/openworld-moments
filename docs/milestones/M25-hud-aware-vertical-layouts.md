# M25 — HUD-aware vertical layouts

## Objective

Produce editable 9:16 layouts that preserve important gameplay and interface regions instead of applying an unsafe center crop.

## Dependencies

M14, M22, and M24 merged.

## Required context

Read specification sections 10.5, 11.4, 12.4, and 16.4.

## In scope

- Fit-with-background, fixed safe crop, and keyed crop strategies.
- Profile-defined protected HUD zones and subject hints.
- Manual crop keyframes with interpolation and preview overlays.
- Conservative automatic framing suggestions with confidence labels.
- 1080×1920 preview and render-plan generation.
- Layout validation against protected regions.

## Out of scope

- Face tracking, fully autonomous cinematic reframing, and direct social publishing.

## Implementation steps

1. Add versioned layout and crop-keyframe contracts to the project model.
2. Load normalized protected zones from the active detector profile.
3. Implement fit, background-fill, fixed-crop, and keyed-crop planners.
4. Add crop handles, safe-zone overlays, strategy selection, and reset controls.
5. Generate low-frequency automatic crop suggestions and suppress unstable results.
6. Compile layouts into M24 render plans without shell interpolation.
7. Add golden frames for common HUD and aspect-ratio cases.

## Acceptance criteria

- A user can render 1080×1920 without altering the horizontal project.
- Fit mode never removes source pixels; crop modes clearly show removed areas.
- Protected zones trigger a warning before export when materially obscured.
- Automatic framing does not visibly jitter on the golden sequences.
- Every automatic decision can be replaced with manual keyframes.
- Preview and rendered crops match within two pixels on golden frames.

## Required validation

- Golden layout, interpolation, safe-zone, rotation, and resolution tests.
- Rapid motion, missing profile, conflicting protected zones, and portrait-source cases.
- End-to-end horizontal-to-vertical project render.

## Handoff

Document layout contracts, interpolation behavior, warning thresholds, profile inputs, golden frames, and known framing limitations. Update M25.
