# M04 — Media probing

## Objective

Turn an explicitly selected local media file into normalized, validated metadata without modifying it.

## Dependencies

M03 merged.

## Required context

Read specification sections 8.1, 8.3, 9.5, and 13.4.

## In scope

- FFmpeg/FFprobe discovery and version capability report.
- Safe subprocess argument construction.
- Probe job handler.
- Normalization of streams, codecs, duration, rational FPS, rotation, audio, and color/HDR metadata.
- Actionable unsupported/damaged-media errors.
- Small synthetic fixture generator for common containers.

## Out of scope

- Copying files, hashes, proxies, thumbnails, and playback.

## Implementation steps

1. Add a managed FFprobe adapter using argument arrays only.
2. Normalize output into M01 media contracts.
3. Implement timeouts, cancellation, stderr bounds, and process cleanup.
4. Generate tiny H.264, HEVC-if-available, no-audio, variable-frame-rate, rotated, and damaged fixtures.
5. Add capability results to a `doctor` command and worker endpoint.
6. Document supported/unsupported metadata behavior.

## Acceptance criteria

- Probe never changes source bytes or modification time.
- Unicode and space-containing paths work.
- Rational frame rates remain rational rather than rounded floats.
- HDR/color metadata is retained when present.
- Damaged or unsupported files produce stable error codes.
- Cancellation terminates FFprobe and completes the job cleanly.

## Required validation

- Fixture matrix tests.
- Path edge-case tests.
- Source hash before/after test.
- Timeout and cancellation test.
- `doctor` output review.

## Handoff

List minimum supported FFmpeg version, capability fields, stable error codes, and fixture-generation command. Update M04.

