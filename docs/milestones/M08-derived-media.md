# M08 — Proxies, thumbnails, and waveforms

## Objective

Create cancellable, cacheable derived media for smooth playback and analysis while preserving original files and color metadata.

## Dependencies

M04 and M05 merged.

## Required context

Read specification sections 8.3, 9.6, 11.2, 11.3, and 12.

## In scope

- Proxy decision policy.
- H.264 SDR proxy generation.
- HDR detection and deterministic tone mapping for proxy only.
- Filmstrip thumbnails.
- Compact waveform data.
- Derived-artifact cache keys, status, cleanup, and regeneration.
- FFmpeg progress/cancellation integration.

## Out of scope

- Final render, captions, dynamic layouts, and source HDR export.

## Implementation steps

1. Define derived artifact contracts and cache-key inputs.
2. Implement proxy necessity decision and generation filter graph.
3. Implement thumbnail sampling and waveform extraction.
4. Write artifacts to temporary paths and atomically promote.
5. Validate proxy duration, streams, and representative decoded frames.
6. Add cache invalidation on tool/preset version change.
7. Add cleanup that never follows paths outside the derived root.

## Acceptance criteria

- Original hash and mtime remain unchanged.
- HDR source creates an SDR proxy with recorded tone-map settings.
- Completed artifacts are never partial.
- Cancelling removes or quarantines temporary outputs.
- Regeneration is deterministic for the same toolchain and preset.
- Missing derived files are rebuildable from canonical state.

## Required validation

- SDR, HDR-metadata, silent, rotated, and VFR fixture tests.
- Cancellation and disk-write failure tests.
- Cache-hit and invalidation tests.
- FFprobe and sampled-decode validation.

## Handoff

Document proxy preset, tone-map filter, cache version, artifact layout, and minimum FFmpeg capabilities. Update M08.

