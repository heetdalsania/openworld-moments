# M21 — Editor project model

## Objective

Implement the non-destructive edit decision model, persistence, validation, autosave, and undo/redo command semantics used by the focused editor and renderer.

## Dependencies

M01, M02, and M13 merged.

## Required context

Read specification sections 8.7, 11.1, and 8.9.3.

## In scope

- Story/project contract with video segments, source ranges, timeline positions, layout references, captions, overlays, and audio ranges.
- Project validation and source availability checks.
- Command-based undo/redo.
- Debounced autosave and crash-safe writes.
- Project migration/versioning and portable JSON export/import.
- Manual project creation from a session selection.

## Out of scope

- Visual timeline UI, rendering, caption transcription, and professional multi-track editing.

## Implementation steps

1. Finalize project schema and invariants.
2. Implement timeline operation library: add, trim, split, delete, reorder.
3. Implement reversible commands and bounded history.
4. Implement transactional autosave and recovery snapshot.
5. Implement project migrations and source relink metadata.
6. Add portable import/export validation.
7. Add property-based timeline tests.

## Acceptance criteria

- Operations cannot create negative, overlapping-invalid, or out-of-source ranges.
- Undo/redo round-trips every operation.
- Crash simulation preserves last committed autosave.
- Missing sources produce relink state without destroying edits.
- Portable project rejects hash-mismatched sources unless user confirms replacement.
- No operation modifies source media.

## Required validation

- Unit and property-based operation tests.
- Autosave crash/reopen test.
- Schema migration and portable round-trip tests.

## Handoff

Document invariants, command API, autosave location/frequency, migration policy, and renderer-facing model. Update M21.

