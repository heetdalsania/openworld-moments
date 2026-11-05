# M22 — Focused editor UI

## Objective

Build the keyboard-accessible clip editor for previewing, trimming, splitting, removing, and reordering the M21 project model.

## Dependencies

M09 and M21 merged.

## Required context

Read specification sections 10.5 and 8.7.1–8.7.2.

## In scope

- Preview synchronized to project timeline.
- Primary-track filmstrip/waveform.
- In/out trim handles and numeric time entry.
- Split, remove, reorder, undo, redo, autosave status.
- Source/event markers as read-only context.
- Aspect-ratio preview frame placeholder ready for M25.
- Keyboard shortcuts and accessible control alternatives.

## Out of scope

- Captions, audio gain, final layouts, rendering, transitions, and multi-track compositing.

## Implementation steps

1. Connect playback clock to project mapping.
2. Render segments and source boundaries.
3. Implement trim/split/remove/reorder through M21 commands only.
4. Add undo/redo and save status.
5. Add keyboard shortcuts and discoverable help.
6. Handle missing proxies/sources and worker failures.
7. Add component and E2E editing tests.

## Acceptance criteria

- UI never mutates project state outside command API.
- Preview follows edits and boundary seeking within one frame tolerance.
- Every pointer operation has a keyboard/numeric alternative.
- Undo/redo visibly restores state and playback mapping.
- Reload restores autosaved project.
- Errors do not discard unsaved edits.

## Required validation

- Component interaction tests.
- Keyboard-only editing walkthrough.
- E2E create/trim/split/reorder/reload test.
- Screenshot or recording for handoff.

## Handoff

Document routes/components, shortcuts, timeline precision, known playback limitations, and test artifacts. Update M22.

