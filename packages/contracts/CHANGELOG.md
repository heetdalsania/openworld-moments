# Contracts changelog

Versions refer to `schema_version` (see [VERSIONING.md](./VERSIONING.md)).

## 1.1 — 2026-11-05 (M03)

Additive; every 1.0 document is valid 1.1.

- `job`: new kind `diagnostic` (synthetic long-running job for tests and UI
  checks); optional `params` (handler input, kept so interrupted jobs can be
  requeued) and `attempt` (run counter).
- `job-event`: new contract for job changes streamed over the worker's
  `/v1/jobs/events` WebSocket, with a per-process `seq` for ordering and gap
  detection.

## 1.0 — 2026-11-05 (M01)

Initial contracts:

- `common`: ID formats, UTC timestamps, timeline milliseconds, rationals,
  normalized regions, confidence, SHA-256, slugs, semantic versions.
- `error`: machine-readable error (unversioned, embedded).
- `evidence`: region template, color rule, OCR, temporal consistency, audio,
  transcript, and model-frame evidence.
- `event`: observation or suggestion with detector/model/user source and review
  state.
- `job`: job kind, state, progress, error, timestamps.
- `media-asset`: identity hashes, capture-time estimate, container, video
  stream with HDR color info, audio streams.
- `profile`: frame constraints, named regions, detector settings, safe zones.
- `project`: edit decision list with crop keyframes, captions, blur overlays,
  audio gain and mute ranges.
- `render-preset`: dimensions, frame rate, video/audio encoding, size cap.
- `export-manifest`: sources, segments, render settings, detector versions,
  normalized command.
