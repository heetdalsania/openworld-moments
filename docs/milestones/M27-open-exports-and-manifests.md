# M27 — Open exports and manifests

## Objective

Export projects, events, captions, timelines, and render provenance in documented formats that do not lock users into this application.

## Dependencies

M21 and M24 merged.

## Required context

Read specification sections 8.8, 8.9, 13.5, and 19.4.

## In scope

- Versioned project JSON and event JSONL exports.
- SRT and WebVTT captions.
- CSV marker export and OpenTimelineIO timeline export.
- Optional experimental FCPXML export behind a stability label.
- Render manifest containing hashes, versions, presets, and source references.
- Export schema documentation and round-trip fixtures.

## Out of scope

- Importing arbitrary third-party editor projects and guaranteeing lossless transfer of unsupported effects.

## Implementation steps

1. Define stable export contracts separately from internal database rows.
2. Implement deterministic project, event, caption, and marker serializers.
3. Map supported project operations into OpenTimelineIO.
4. Generate a machine-readable manifest for every completed render.
5. Add schema versions, capability declarations, and forward-compatible unknown fields.
6. Build validators and deterministic golden exports.
7. Publish examples and limitations with each format.

## Acceptance criteria

- Re-exporting unchanged data produces byte-stable JSON/JSONL and manifests.
- Caption timing matches the project timeline within one frame.
- OTIO exports open in the project’s documented reference viewer or validator.
- Manifests identify source hashes, project revision, detector/profile versions, FFmpeg version, and preset.
- Exports contain no absolute source path unless the user explicitly selects that option.
- Unsupported operations produce warnings rather than silent data loss.

## Required validation

- Schema, deterministic serialization, Unicode, escaping, and round-trip tests.
- Missing-source and unsupported-operation fixtures.
- External OTIO validation and caption playback spot check.

## Handoff

Document every export version, privacy option, compatibility result, unsupported feature, fixture, and validation command. Update M27.
