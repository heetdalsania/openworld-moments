# M36 — macOS media and render parity

## Objective

Deliver correct playback, proxy generation, analysis, and horizontal/vertical rendering on both Mac architectures, with capability-tested VideoToolbox acceleration and safe CPU fallback.

## Dependencies

M25, M33, and M34 merged.

## Required context

Read specification sections 8.5, 11, 12, and 21.1 plus the macOS delivery plan.

## In scope

- H.264, HEVC, variable-frame-rate, rotation, no-audio, and supported HDR fixtures.
- Proxy-generation parity with Windows.
- VideoToolbox decode/encode capability probes.
- Visible CPU fallback with preserved quality/preset semantics.
- Horizontal and HUD-aware vertical render parity.
- Color metadata, HDR-to-SDR behavior, audio sync, and output validation.
- Performance/thermal measurements on representative Apple Silicon and Intel Macs.

## Out of scope

- Metal-native ML rewrites, Apple ProRes licensing promises, and guaranteed real-time performance on every Mac.

## Implementation steps

1. Add a versioned macOS media capability probe and report.
2. Validate embedded playback and proxy rules against the codec fixture matrix.
3. Add VideoToolbox presets behind successful short capability renders.
4. Preserve CPU presets as the correctness baseline and implement explicit fallback reasons.
5. Validate color tags and controlled HDR-to-SDR conversion.
6. Compare preview and rendered crops, captions, duration, frames, and audio sync.
7. Record performance, memory, temperature/thermal-state observations, and disk usage.

## Acceptance criteria

- Every supported fixture either plays correctly or receives a validated proxy.
- CPU renders match golden duration, layout, caption, audio, and color expectations on both architectures.
- VideoToolbox is offered only after the exact codec/pixel-format probe passes.
- Hardware failure falls back visibly without silently changing output dimensions or timing.
- HDR input cannot produce an untagged or visibly washed-out default export.
- Preview-to-render crop difference remains within the existing golden tolerance.

## Required validation

- Full codec/proxy/render golden matrix on Apple Silicon and Intel.
- VideoToolbox success, unsupported format, mid-render failure, cancellation, and CPU fallback cases.
- Sampled-frame color, black-frame, A/V sync, rotation, and output FFprobe audits.

## Handoff

Document fixture licenses, tested hardware/OS versions, capability rules, FFmpeg configuration, VideoToolbox results, CPU baselines, color decisions, performance data, and unsupported media cases. Update M36.
