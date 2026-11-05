# M16 — Wanted-state detector

## Objective

Implement the first production-style temporal detector: infer stable wanted-level state changes from a calibrated HUD region and emit explainable events.

## Dependencies

M15 merged.

## Required context

Read specification sections 8.4.3 and 8.4.4. Do not use leaked footage or extracted game assets.

## In scope

- Generic star/indicator-state detection using lawful synthetic fixtures and user-local calibration.
- Zero-to-maximum state representation.
- Temporal confirmation, tolerated misses, debounce, and change events.
- Evidence crops referenced locally but not embedded in shareable events.
- Confidence and performance metrics.
- Conservative compatibility status: unvalidated for GTA VI until legitimate evaluation exists.

## Out of scope

- Police recognition, chase semantics, input actions, or bundled official UI templates.

## Implementation steps

1. Generate synthetic indicator fixtures with scale, compression, brightness, and occlusion variants.
2. Implement preprocessing and state estimator.
3. Implement temporal state machine and transition events.
4. Add explainable evidence scores.
5. Integrate profile ROI and calibration overrides.
6. Add replay trace output and benchmark.
7. Document unvalidated status and local-evaluation procedure.

## Acceptance criteria

- Synthetic transitions produce one correct event after confirmation.
- Brief occlusion/compression does not cause flicker.
- Sustained zero state clears wanted level correctly.
- Ambiguous frames lower confidence or produce unknown rather than a false state.
- Processing meets the deterministic detector budget on reference hardware.
- No official game asset is committed.

## Required validation

- Transition, flicker, occlusion, scaling, compression, and false-pattern tests.
- Performance benchmark and trace review.
- Local unvalidated profile smoke test if lawful footage is available, without committing it.

## Handoff

Document algorithm, confirmation settings, confidence, benchmark, fixture provenance, and exact validation status. Update M16.

