# M24 — Render engine

## Objective

Compile validated project data into safe FFmpeg argument graphs, render cancellable horizontal exports, and validate outputs before marking them complete.

## Dependencies

M04 and M21 merged.

## Required context

Read specification sections 11, 8.9, 12.5, and 13.4.

## In scope

- Versioned render preset schema.
- Project-to-FFmpeg graph compiler using argument arrays.
- Source trim/concat, simple crop/scale, audio gain/mute, basic text overlay hooks.
- CPU H.264/AAC baseline.
- Hardware encoder capability probes and explicit fallback.
- Progress, cancellation, temporary output, atomic completion.
- FFprobe and sampled-decode validation.

## Out of scope

- HUD-aware dynamic layouts, OTIO export, direct publishing, and HDR-preserving output.

## Implementation steps

1. Define render plan intermediate representation.
2. Compile M21 project segments and audio operations.
3. Implement baseline and capability-tested hardware presets.
4. Parse FFmpeg progress and support cancellation.
5. Validate duration, streams, resolution, audio, black frames, and rotation.
6. Store normalized render plan and tool versions.
7. Add golden projects and failure fixtures.

## Acceptance criteria

- User-controlled paths/text never pass through a shell command string.
- Output duration is within 100 ms of target golden projects.
- Cancellation leaves no file marked complete.
- Hardware failure produces a visible CPU fallback choice, not silent quality change.
- Validation catches malformed/empty output.
- Source files remain unchanged.

## Required validation

- Golden single/multi-segment, mute/gain, Unicode path, and no-audio renders.
- Cancellation, encoder-failure, disk-full, and validation-failure tests.
- FFprobe output audit.

## Handoff

Document render IR, presets, hardware probes, validation thresholds, tool versions, and golden outputs. Update M24.

