# Contracts changelog

## 1.24 — Diagnostics report (M31)

- Add the diagnostics-report contract: versions, system check, library counts, job totals and recent failure codes. Its privacy block is fixed by the schema (no footage, file names, paths or tokens), and a semantic rule rejects failure messages unless the user opted in.
- Existing 1.x documents remain readable.

## 1.23 — Windows runtime and optional model management (M29)

- Add model-manager and system-doctor contracts, shared semantic consistency rules and fixtures.
- Add durable model_download jobs; queued jobs pin the selected SHA-256 across restarts/upgrades.
- Existing 1.x projects, events, speech-model status and exports remain readable.
- Generate standalone TypeScript validators so packaged CSP can prohibit runtime string evaluation; validation and compatibility rules are unchanged.

Versions refer to `schema_version` (see [VERSIONING.md](./VERSIONING.md)).

## 1.22 — M28 privacy and spoiler review

- Add `privacy-review` findings/configuration/decisions and text-free gate summaries.
- Add optional fixed-size linear privacy-blur `keyframes` to Project overlays and render IR.
- Add optional `privacy_review` summaries to render plans, manifests and export results.
- Project JSON and event JSONL preserve summaries under `extensions`; older 1.x documents remain valid.
- New project exports/renders require current creator review. Caption sidecars use the gated `project_export` host command; the ungated `caption_export` command is removed.

## 1.21 — M27 open exports

Additive; existing 1.20 documents remain valid.

- New `export-result` contract (`ExportResult`): format, format version, stability
  (FCPXML experimental), filename, media type, content and its SHA-256,
  capabilities, warnings (`export.*` codes) and whether paths are included. `$defs`
  add `ExportWarning`, `ExportGenerator` and `ExportRequest`.
- New `project-export` contract (`ProjectExport`, format `openworld-moments.project`
  1.x): the portable editor document with revision, saved time, capabilities,
  warnings, optional `source_locations` and an `extensions` object.
- New `event-export` contract (`EventExportLine`): a JSONL header or an event record
  with the original observation, the effective review view, timing status and
  project ranges.
- `export-manifest` gains optional `render_id`, `project_revision`, `encoder`,
  `tools`, `output` and `profiles`.
- Shared cross-field rules: FCPXML is the only experimental format; paths only in
  project, OTIO and FCPXML; locations name document sources; ordered event ranges.
  Migration 0017 stores each render's manifest.

## 1.20 — M26 search and collections

Additive; existing 1.19 documents remain valid.

- New `search` contract (`SearchResults`): parsed query (terms and ignored items),
  filters, page, results and facets, index status and timing. `SearchResult` carries
  a `<kind>:<id>` key, `{text, match}` title/snippet segments (never markup), the
  matched fields, IDs, the exact `range` (session or clip time), an optional source
  range and document metadata. `$defs` add `SearchRequest`, `SearchFilters`,
  `TextSegment`, `SearchFacet` and `MatchReason`.
- New `search-index` contract (`SearchIndexStatus`): index version, status
  (current, stale, rebuilding, cleared, corrupt), reasons, per-kind counts and
  whether a full check ran.
- New `collection` contract (`Collection`): manual or rule-based, with one page of
  results; rule items carry reasons, manual items carry item IDs. `$defs` add
  `CollectionRule` (grammar version 1), `CollectionSummary`, `CollectionCreate`,
  `CollectionUpdate` and `CollectionItemRef`. Common adds `CollectionId` (`col_`).
- Shared cross-field rules: keys match kind and ID, ordered ranges, clip time only
  for clips, page and facet bounds, reasons only on rule items, status/reason
  consistency. Migration 0016 adds the search index and reshapes collections.

## 1.19 — M25 vertical layouts

- Optional `Segment.vertical_crop` layout version 1: independent fit/fixed/keyed
  framing, solid/blurred background and fixed-size smoothstep position keyframes.
- Optional saved static suggestion provenance (algorithm, confidence, explanation,
  profile identity); profile `subject_hints` references named normalized regions.
- Render-plan pieces optionally retain vertical settings and upright source sizes;
  plans optionally retain the effective calibrated profile. Plan version stays 1.
- Render requests add explicit layout review and an optional expected project
  revision. No SQL migration or editor-model version change.
- Shared valid/invalid fixtures cover bounds, key times, dimensions and strategies.

## 1.18 — M24 render engine

Additive; existing 1.17 documents remain valid.

- New `render` contract (`RenderRecord`): status, preset, encoder, project revision,
  the normalized `RenderPlan` IR (plan_version 1; argv template with placeholders,
  no paths or user text), `RenderValidation` (checks, FFprobe audit, thresholds),
  library-relative `RenderOutput`, error, and an explicit CPU `fallback`. A `ready`
  record requires a passed validation; only failed records offer a fallback;
  `omitted` may list text only, never privacy blur.
- New `render-encoders` contract: encoders with test-encode availability, reasons and
  quality notes. libx264 is the only CPU encoder.
- `RenderRequest` (`preset_id`, `encoder?`, `omit_text?`) in `render.$defs`.

## 1.17 — M23 captions and audio controls

- Optional `Project.caption_settings`: high-contrast/compact preset, normalized
  output-frame region, burn-in choice and none/SRT/VTT/both sidecar intent.
- Region bounds match in TypeScript/Python. Legacy 1.x documents remain readable;
  missing caption settings use desktop defaults. Model version remains 1 and no
  SQL migration is needed. Existing captions/audio/range units are unchanged.
- New shared valid/out-of-bounds/unknown-style fixtures; readers reject 1.18.

## 1.16 — 2026-11-07 (M21)

Additive: `editor-project` wraps the existing Project with explicit editor model
version 1, aspect/profile layout reference and portable SHA-256 source bindings.
The new envelope enforces single-track contiguous timing, source containment,
unique segment IDs, bounded annotations and ordered crop keyframes in both SDKs.
Project gains optional audio gain ranges and a text overlay variant; older 1.x
Project documents remain readable. Legacy projects migrate explicitly on editor
open and commit on first save. Migration 0014 stores transactional autosave and
recovery snapshots. See [editor projects](../../docs/architecture/editor-projects.md).

## 1.15 — 2026-11-07 (M20)

Additive: `story-candidate` (versioned deterministic windows, source-event revisions,
source ranges, beats, alternatives, decomposed scores, coverage and warnings),
`story-candidates` (paged review/freshness projection), and the `story` job kind.
Shared TS/Python checks cover gap-free nonduplicated ranges, exact score sums and
weight bounds, event references, preset maxima and current-page identity.
Migration 0013 stores immutable candidates, append-only decisions and generation
cache markers; explicit acceptance uses the existing Project/Story contract.

## 1.14 — 2026-11-07 (M19)

Additive: `event-review` (original/effective observations, status and bounded recent
append-only decision history), `evaluation` (hash-addressed annotated holdouts),
`evaluation-observations` (text-free frozen predictions/performance), and
`evaluation-report` (metrics and compatibility rows). Shared TS/Python checks
cover immutable review fields, history, unique media hashes and interval bounds.
Migration 0012 stores immutable observations and separate human decisions.

## 1.13 — 2026-11-07 (M18)

Additive; existing 1.12 documents remain valid.

- `evidence.AudioEvidence`: optional `feature` (`loudness`, `onset`, `impact`,
  `silence`, `speech_activity`), `level_dbfs` (−160..0) and `role`, which can only be
  `supporting`. Audio is corroborating evidence, never a highlight claim.
- `profile.capabilities`: adds `audio.pcm`.
- New `transcript` (session segments with words, source and session times,
  language, confidence and transcriber provenance; no speaker field), `transcription`
  (per-clip job result) and `speech-models` (engine status, installed models and
  catalog for manual installation). TS/Python check segment/word ordering and
  containment, unique outcomes and models, and that an unavailable engine gives a
  reason.
- SDK 1.3.0 adds immutable `AudioSamples` and `AnalysisContext.audio`. Migration
  0011 extends `transcript_segments` and adds `transcript_runs`.

## 1.12 — 2026-11-07 (M17)

Additive; existing 1.11 documents remain valid.

- `profile.LocalePack.ocr_language`: optional installed local language ID (no paths/URLs).
- `profile.DetectorSettings.ocr`: bounded contrast/threshold preprocessing, text
  confidence, whole-text match threshold and missing-sample settings.
- `evidence.OcrEvidence`: optional source `frame_ms` and bounded `lines` with text,
  global normalized box and confidence. TS/Python verify picture and parent-crop
  containment. Existing region/text/score-only OCR evidence remains readable.
- SDK 1.2.0 supports nested immutable line evidence, fixed trusted OCR sampling and
  optional local OCR preparation/provenance in the existing registry. No migration.

## 1.11 — 2026-11-07 (M16)

Additive; existing 1.10 documents remain valid.

- `profile.DetectorSettings.wanted`: optional bounded analytic settings (`max_level`
  1–10, `shape` star/disc, `max_missing_frames` 0–20, `debounce_ms` 0–30000).
  This is data only; no executable templates or filter expressions.
- `evidence.RegionTemplateEvidence.frame_ms`: optional source timestamp. Together
  with the event asset ID, normalized region and input provenance, this identifies
  a locally reconstructable crop. Events contain no image bytes or local paths.
- SDK 1.1.0 separately adds immutable `Frame.region` metadata for trusted built-in
  ROI sampling; existing whole-frame consumers retain `region=None`.

## 1.10 — 2026-11-06 (M15)

Additive; existing 1.9 documents remain valid.

- New `profile-patch`: media-free sparse normalized ROI overrides, base identity,
  compatibility and tool provenance. Both runtimes reject unknown fields and
  out-of-bounds regions; the calibration worker also validates the effective M14
  profile before storage or preview. Installed profiles remain immutable.

## 1.9 — 2026-11-06 (M14)

Additive; existing 1.8 documents remain valid.

- `profile`: optional `extends`, `license`, `capabilities`, and versioned, licensed
  `locales` vocabulary packs. The analysis loader requires license/capability
  metadata, validates resolved inheritance, and refuses duplicate detector IDs.
- `event.DetectorSource`: optional `tool_versions` and SHA-256 `input_key`.
  M14's runtime always supplies detector/profile/tool versions and input identity.
- New `analysis` result: per-clip/per-detector computed, cached, failed, or skipped
  outcomes. Failed/skipped outcomes must carry an error and no event IDs.
  `$defs/AnalysisRequest` describes profile, locale and forced recomputation.
- The existing `analyze` job kind and `analyzing` state are now implemented.

## 1.8 — 2026-11-07 (M12)

Additive; every 1.7 document is valid 1.8.

- `overlap` (new): `AssetOverlap`, the alignment of clip B after clip A (status
  `matched` / `weak` / `ambiguous` / `no_match` / `insufficient` / `pending`,
  offset, overlap, confidence, evidence, algorithm version, whether current,
  user override, and what is applied), with `$defs` `AlignRequest`,
  `AlignResult`, and `OverlapOverride`. Semantic rules: different assets; matched
  results carry offset, overlap, and confidence; an override is what applies;
  only a current matched result applies automatically.
- `session`: `SessionMember` gains `overlap_with_previous_ms` and
  `alignment_confidence`; `SessionCorrection.kind` gains `overlap`. Semantic
  rule: the first member has no overlap.
- `job`: new kind `align`.

## 1.7 — 2026-11-07 (M11)

Additive; every 1.6 document is valid 1.7.

- `session` (new): `Session`, a candidate play session with ordered members
  (`SessionMember`: order, start within the session, duration, capture-time
  estimate), review state, confidence, and `SessionGrouping` evidence
  (algorithm, version, max gap, per-join `GroupingLink` with gap, confidence,
  and reasons; split reasons; capture-time notes). `$defs` also cover
  `GroupRequest` / `GroupResult` (the `group` job), the correction requests, and
  `SessionCorrection` (the log). Semantic rules: order indexes run 0..n-1,
  starts never decrease, no duplicate members, `ended_at` not before
  `started_at`, links join adjacent members.
- `job`: new kind `group`.

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
