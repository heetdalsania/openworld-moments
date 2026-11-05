# M23 — Captions and audio controls

## Objective

Add transcript-backed caption correction and simple non-destructive audio controls to the focused editor.

## Dependencies

M18 and M22 merged.

## Required context

Read specification sections 8.7.4 and 8.8.1.

## In scope

- Convert transcript segments/words into editable caption cues.
- Add, remove, split, merge, retime, and correct cues.
- Caption style preset and safe-area preview.
- Burn-in toggle plus SRT/VTT sidecar state.
- Segment/range mute and project/segment gain.
- Waveform visualization integration.
- Warning for mixed audio that cannot separate voice chat/music.

## Out of scope

- Dubbing, translation, stem separation, noise removal, and advanced mixing.

## Implementation steps

1. Add caption/audio fields and commands to M21 model.
2. Build caption list/timeline editing UI.
3. Implement word-to-cue initialization and retiming.
4. Add safe-zone preview and accessible style controls.
5. Add mute/gain ranges and preview behavior.
6. Implement SRT/VTT serializer tests.
7. Document audio limitations.

## Acceptance criteria

- Caption text/times survive project reload.
- Cue operations maintain sorted nonnegative intervals.
- Muted ranges affect preview representation and later render model.
- SRT/VTT round-trip expected Unicode and multiline text.
- Caption placement warns on configured HUD/subtitle conflicts.
- No claim of audio-source separation is made for mixed tracks.

## Required validation

- Caption command/unit tests.
- SRT/VTT golden files.
- UI E2E correction/mute/reload test.
- Keyboard and screen-reader form review.

## Handoff

Document caption model, serialization rules, audio gain units, shortcuts, and limitations. Update M23.

