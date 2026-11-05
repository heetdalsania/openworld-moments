# M13 — Virtual session timeline

## Objective

Provide synchronized playback across ordered source assets while hiding confirmed duplicate overlap and retaining traceability to original time.

## Dependencies

M09 and M12 merged.

## Required context

Read specification sections 10.4, 12.4, and session asset data model.

## In scope

- Bidirectional source-time ↔ virtual-session-time mapping.
- Multi-asset playback controller.
- Timeline source boundaries and hidden-overlap visualization.
- Seek, play, pause, and frame-step around boundaries.
- Toggle to reveal duplicated ranges.
- Session merge/split/reorder integration.

## Out of scope

- Event markers, story editing, captions, and final render.

## Implementation steps

1. Implement pure mapping library with exhaustive tests.
2. Create playback controller that switches sources without losing virtual clock.
3. Render filmstrip/waveform across assets.
4. Visualize overlap and confidence.
5. Add manual order/boundary controls tied to M11 overrides.
6. Add keyboard controls and loading/error behavior.
7. Add E2E session playback fixture.

## Acceptance criteria

- Mapping round trips within one frame for supported frame rates.
- Playback crosses an asset boundary without replaying confirmed overlap.
- User can reveal and inspect hidden duplicate time.
- Seeking to event-ready timestamps selects the correct source.
- Reordering recomputes mappings without corrupting session data.
- Keyboard controls work across the full timeline.

## Required validation

- Unit tests for zero/partial/full overlap and VFR metadata.
- A/V sync boundary smoke test.
- E2E seek/play/reorder test.

## Handoff

Document mapping API, precision guarantees, player limitations, and source-boundary behavior. Update M13.

