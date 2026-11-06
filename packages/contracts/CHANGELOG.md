# Contracts changelog

Versions refer to `schema_version` (see [VERSIONING.md](./VERSIONING.md)).

## 1.6 — 2026-11-06 (M08)

Additive; every 1.5 document is valid 1.6.

- `derived-media` (new): `AssetDerivedMedia`, an asset's proxy decision (with
  reasons and policy version) and one `DerivedArtifact` per kind (proxy,
  filmstrip, waveform) with status, cache key, library-relative path, digest,
  recipe, last error, and kind-specific info (`ProxyInfo` with an optional
  `ToneMap`, `FilmstripInfo`, `WaveformInfo`). `$defs` also cover
  `DerivedMediaRequest` (params of the `proxy` job), `DerivedMediaResult`, and
  `DerivedCleanupResult`. Semantic rules: kinds in order; complete states carry
  path, digest, recipe, and info, and other states carry none; a failed
  artifact carries `last_error`; filmstrip counts match ascending times; a
  proxy has `tone_map` exactly when tone-mapped; `needed` matches the reasons.
- `job`: the existing `proxy` kind is now used (result: `DerivedMediaResult`).

## 1.5 — 2026-11-06 (M07)

Additive; every 1.4 document is valid 1.5.

- `watched-folder` (new): `WatchedFolder` (path, source kind, mode, recursion,
  include/exclude patterns, enabled, availability, last scan, last error,
  per-state file counts), with `$defs` `WatchedFolderRequest`,
  `WatchedFileReport`, `WatchedFileDecision`, `WatchedFile`, `ScanReport`,
  `Patterns`, and `SourceKind`. Semantic rule: per-state counts fit in
  `stats.tracked`.
- Shared pattern cases for host and worker:
  `fixtures/watched-folder/patterns.json`.

## 1.4 — 2026-11-06 (M06)

Additive; every 1.3 document is valid 1.4.

- `fingerprint` (new): `AssetFingerprints` (exact SHA-256, `owm-fast` fast
  hash, `dhash256` frame hashes over head/tail windows, `energy-envelope`
  audio), each with algorithm and version, plus `$defs` `DuplicateCandidate`,
  `DuplicateEvidence`, `FingerprintRequest`, and `FingerprintResult`.
- `job`: new kind `fingerprint` (backfill).
- `import`: `ImportItem.candidate_asset_ids` (perceptual look-alikes, review
  only). Semantic rule: only items with an asset may carry it.

## 1.3 — 2026-11-05 (M05)

Additive; every 1.2 document is valid 1.3.

- `import` (new): `ImportResult`, the per-file report of an import job, with
  `$defs` `ImportRequest` (import job params), `ImportItem`, `ImportTotals`,
  `RelinkRequest`, `RelinkResult`, and `SourceCheckResult`. Semantic rules:
  items with an asset carry `asset_id` and no `error`; skipped and failed items
  carry `error`; `totals` match `items`.
- `job`: new kinds `relink` and `check_sources`; optional `idempotency_key`;
  `result` may also be set on a failed import.
- `media-asset`: optional `size_bytes` (source size at import).

## 1.2 — 2026-11-05 (M04)

Additive; every 1.1 document is valid 1.2.

- `job`: new kind `probe`; optional `result` (handler output, set on `ready`;
  a `MediaProbe` for probe jobs).
- `media-asset`: new `$defs/MediaProbe` (normalized FFprobe result before
  import). `VideoStream` gains optional `average_frame_rate`,
  `variable_frame_rate`, and `rotation` (clockwise 0/90/180/270). `ColorInfo`
  gains optional `range`, `mastering_display`, `content_light_level`, and
  `dolby_vision`. `AudioStream` gains optional `channel_layout`.

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
