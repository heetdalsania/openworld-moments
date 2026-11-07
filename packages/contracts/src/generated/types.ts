// SPDX-License-Identifier: Apache-2.0
// GENERATED FILE. Do not edit by hand.
// Source: packages/contracts/schemas/*.schema.json
// Regenerate with: pnpm contracts:generate

/**
 * Opaque session ID: 'ses_' + ULID.
 */
export type SessionId = string;
/**
 * Lowercase identifier for profiles, presets, detectors, and regions.
 */
export type Slug = string;
/**
 * Opaque media asset ID: 'ast_' + ULID.
 */
export type AssetId = string;
/**
 * Opaque event ID: 'evt_' + ULID.
 */
export type EventId = string;
/**
 * Primitive value allowed in open attribute maps.
 */
export type ScalarValue = string | number | boolean | null;
/**
 * Opaque request/log correlation ID: 'cor_' + ULID.
 */
export type CorrelationId = string;
/**
 * 'auto': a proxy only when the policy finds a reason. 'always': a proxy for every asset.
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "ProxyPolicy".
 */
export type ProxyPolicy = "auto" | "always";
/**
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "DerivedKind".
 */
export type DerivedKind = "proxy" | "filmstrip" | "waveform";
/**
 * Lowercase hex SHA-256 digest.
 */
export type Sha256 = string;
/**
 * Lowercase hex SHA-256 digest.
 */
export type Sha2561 = string;
/**
 * RFC 3339 timestamp in UTC with a literal 'Z' suffix and at most millisecond precision.
 */
export type UtcTimestamp = string;
/**
 * Position on a media or session timeline in integer milliseconds from its start.
 */
export type TimelineMs = number;
/**
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "DerivedOutcome".
 */
export type DerivedOutcome = "generated" | "cached" | "not_needed" | "not_applicable";
/**
 * Probability-like score in [0, 1].
 */
export type Confidence = number;
/**
 * One piece of support for an event. Discriminated by 'kind'. Embedded in events.
 */
export type Evidence =
  | RegionTemplateEvidence
  | ColorRuleEvidence
  | OcrEvidence
  | TemporalConsistencyEvidence
  | AudioEvidence
  | TranscriptEvidence
  | ModelFrameEvidence;
/**
 * Normalized rectangle [x, y, width, height] relative to the frame, origin top-left. Width and height must be positive and the rectangle must lie inside the frame (checked semantically).
 *
 * @minItems 4
 * @maxItems 4
 */
export type Region = [x: number, y: number, width: number, height: number];
/**
 * Position on a media or session timeline in integer milliseconds from its start.
 */
export type TimelineMs1 = number;
/**
 * Semantic version without build metadata, e.g. '0.3.0' or '1.2.0-beta.1'.
 */
export type SemVer = string;
/**
 * Opaque project ID: 'prj_' + ULID.
 */
export type ProjectId = string;
/**
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "AlgorithmVersion".
 */
export type AlgorithmVersion = number;
/**
 * 'reference' keeps the file where it is; 'managed' copies it into the library's content-addressed storage. Moving is not offered (spec 8.1.3).
 *
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "ImportMode".
 */
export type ImportMode = "reference" | "managed";
/**
 * Opaque job ID: 'job_' + ULID.
 */
export type JobId = string;
/**
 * Non-negative duration in integer milliseconds.
 */
export type DurationMs = number;
/**
 * RFC 3339 timestamp in UTC with a literal 'Z' suffix and at most millisecond precision.
 */
export type UtcTimestamp1 = string;
/**
 * Position on a media or session timeline in integer milliseconds from its start.
 */
export type TimelineMs2 = number;
/**
 * Opaque timeline segment ID: 'seg_' + ULID.
 */
export type SegmentId = string;
/**
 * RFC 3339 timestamp in UTC with a literal 'Z' suffix and at most millisecond precision.
 */
export type UtcTimestamp2 = string;
/**
 * RFC 3339 timestamp in UTC with a literal 'Z' suffix and at most millisecond precision.
 */
export type UtcTimestamp3 = string;
/**
 * Position on a media or session timeline in integer milliseconds from its start.
 */
export type TimelineMs3 = number;
/**
 * Position on a media or session timeline in integer milliseconds from its start.
 */
export type TimelineMs4 = number;
/**
 * Probability-like score in [0, 1].
 */
export type Confidence1 = number;
/**
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "GroupingReason".
 */
export type GroupingReason =
  | "same_source"
  | "compatible_format"
  | "gap_within_limit"
  | "overlapping"
  | "time_unknown"
  | "import_order"
  | "codec_changed"
  | "resolution_changed"
  | "frame_rate_changed"
  | "gap_exceeded";
/**
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "SourceKind".
 */
export type SourceKind = "xbox" | "playstation" | "obs" | "capture_card" | "phone_upload" | "other";
/**
 * Glob patterns over '/'-separated paths relative to the folder, matched case-insensitively. A pattern without '/' matches the file name; one with '/' matches the whole relative path. '*' and '?' stay within one path segment; '**' spans segments. Only supported video files are ever candidates, whatever 'include' says.
 *
 * @maxItems 32
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "Patterns".
 */
export type Patterns = string[];
/**
 * RFC 3339 timestamp in UTC with a literal 'Z' suffix and at most millisecond precision.
 */
export type UtcTimestamp4 = string;

export interface ContractsBundle {
  analysis?: AnalysisResult;
  "derived-media"?: AssetDerivedMedia;
  error?: ErrorInfo;
  event?: Event;
  evidence?: Evidence;
  "export-manifest"?: ExportManifest;
  fingerprint?: AssetFingerprints;
  import?: ImportResult;
  "job-event"?: JobEvent;
  job?: Job;
  "media-asset"?: MediaAsset;
  overlap?: AssetOverlap;
  "profile-patch"?: ProfilePatch;
  profile?: Profile;
  project?: Project;
  "render-preset"?: RenderPreset;
  session?: Session;
  "watched-folder"?: WatchedFolder;
}
export interface AnalysisResult {
  schema_version: string;
  session_id: SessionId;
  profile_id: Slug;
  outcomes: DetectorOutcome[];
}
/**
 * This interface was referenced by `AnalysisResult`'s JSON-Schema
 * via the `definition` "DetectorOutcome".
 */
export interface DetectorOutcome {
  asset_id: AssetId;
  detector_id: Slug;
  status: "computed" | "cached" | "failed" | "skipped";
  event_ids: EventId[];
  error?: ErrorInfo;
}
/**
 * Machine-readable error shared by the worker API, jobs, and the desktop host. Embedded in other documents, so it has no schema_version of its own.
 */
export interface ErrorInfo {
  /**
   * Stable dotted snake_case code, e.g. 'media.probe_failed'. Never localized.
   */
  code: string;
  /**
   * Human-readable explanation. Must not contain media contents or transcripts.
   */
  message: string;
  retryable: boolean;
  /**
   * Extra machine-readable context. Values are scalars only.
   */
  details?: {
    [k: string]: ScalarValue | undefined;
  };
  /**
   * Last lines of a tool's stderr (e.g. FFmpeg), already redacted of user paths.
   */
  stderr_tail?: string;
  correlation_id?: CorrelationId;
}
/**
 * This interface was referenced by `AnalysisResult`'s JSON-Schema
 * via the `definition` "AnalysisRequest".
 */
export interface AnalysisRequest {
  profile_id: Slug;
  /**
   * BCP 47 language tag, e.g. 'en' or 'pt-BR'.
   */
  locale?: string;
  force?: boolean;
}
/**
 * Derived playback media of one asset (spec 8.3, M08): the proxy decision and the state of each artifact (proxy, filmstrip thumbnails, waveform). Artifacts are replaceable files under library/derived/<asset-id>/; 'path' is relative to the library folder. Each artifact records its recipe and a cache key over the asset's SHA-256, the kind, and the recipe; an artifact whose key differs from the current one is 'stale'.
 */
export interface AssetDerivedMedia {
  schema_version: string;
  asset_id: AssetId;
  proxy_decision: ProxyDecision;
  /**
   * Exactly one entry per kind, in the order proxy, filmstrip, waveform (checked semantically).
   *
   * @minItems 3
   * @maxItems 3
   */
  artifacts: [DerivedArtifact, DerivedArtifact, DerivedArtifact];
}
/**
 * Whether the embedded player needs a proxy, with every reason. 'needed' is true exactly when 'reasons' is non-empty and does not only contain 'no_video' (checked semantically).
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "ProxyDecision".
 */
export interface ProxyDecision {
  needed: boolean;
  policy: ProxyPolicy;
  policy_version: number;
  /**
   * @maxItems 16
   */
  reasons:
    | []
    | [ProxyReason]
    | [ProxyReason, ProxyReason]
    | [ProxyReason, ProxyReason, ProxyReason]
    | [ProxyReason, ProxyReason, ProxyReason, ProxyReason]
    | [ProxyReason, ProxyReason, ProxyReason, ProxyReason, ProxyReason]
    | [ProxyReason, ProxyReason, ProxyReason, ProxyReason, ProxyReason, ProxyReason]
    | [ProxyReason, ProxyReason, ProxyReason, ProxyReason, ProxyReason, ProxyReason, ProxyReason]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ]
    | [
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason,
        ProxyReason
      ];
}
/**
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "ProxyReason".
 */
export interface ProxyReason {
  code:
    | "requested"
    | "container"
    | "codec"
    | "pixel_format"
    | "hdr"
    | "resolution"
    | "frame_rate"
    | "audio_codec"
    | "no_video";
  detail: string;
}
/**
 * One artifact's state. 'ready': complete and current. 'stale': complete but made with an older preset, policy, or FFmpeg build (still playable; regenerate to update). 'missing': recorded but the file is gone (rebuildable). 'failed': never produced; see last_error. 'not_generated': not made yet. 'not_needed': no proxy is needed. 'not_applicable': no waveform for an asset without audio. Complete states (ready, stale, missing) carry path, size, digest, recipe, and the kind's info object (checked semantically).
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "DerivedArtifact".
 */
export interface DerivedArtifact {
  kind: DerivedKind;
  status:
    "ready" | "stale" | "missing" | "failed" | "not_generated" | "not_needed" | "not_applicable";
  cache_key?: Sha256;
  /**
   * Relative to the library folder: derived/<asset-id>/<kind>-<key16>[.mp4|.bin]. A filmstrip path is a folder.
   */
  path?: string;
  size_bytes?: number;
  sha256?: Sha2561;
  created_at?: UtcTimestamp;
  recipe?: Recipe;
  last_error?: ErrorInfo1;
  proxy?: ProxyInfo;
  filmstrip?: FilmstripInfo;
  waveform?: WaveformInfo;
}
/**
 * How an artifact was made: the versioned preset, the FFmpeg build, and the parameters chosen for this asset. Part of the cache key.
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "Recipe".
 */
export interface Recipe {
  /**
   * The preset as used, with all of its parameters (open: each preset id defines its own fields; 'version' changes whenever they do).
   */
  preset: {
    id: string;
    version: number;
    [k: string]: unknown | undefined;
  };
  policy_version?: number;
  tool: {
    ffmpeg: string | null;
    libraries: {
      [k: string]: string | undefined;
    };
  };
  output?: {
    [k: string]: ScalarValue | undefined;
  };
  tone_map?: ToneMap | null;
  /**
   * Filmstrip input: the proxy (by cache key) or the original file.
   */
  source?: {
    kind: "proxy" | "original";
    cache_key?: Sha256;
  };
}
/**
 * The deterministic HDR-to-SDR mapping used for a proxy: a 3D LUT computed by the worker and applied with FFmpeg's lut3d filter. Same settings give a byte-identical LUT ('lut_sha256').
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "ToneMap".
 */
export interface ToneMap {
  /**
   * Source transfer: PQ (HDR10) or HLG.
   */
  transfer: "smpte2084" | "arib-std-b67";
  method: "lut3d";
  curve: "hable";
  source_peak_nits: number;
  reference_white_nits: number;
  output_primaries: "bt709";
  output_transfer: "bt709";
  lut_size: number;
  interpolation: "tetrahedral" | "trilinear" | "nearest";
  version: number;
  lut_sha256: Sha256;
}
/**
 * Machine-readable error shared by the worker API, jobs, and the desktop host. Embedded in other documents, so it has no schema_version of its own.
 */
export interface ErrorInfo1 {
  /**
   * Stable dotted snake_case code, e.g. 'media.probe_failed'. Never localized.
   */
  code: string;
  /**
   * Human-readable explanation. Must not contain media contents or transcripts.
   */
  message: string;
  retryable: boolean;
  /**
   * Extra machine-readable context. Values are scalars only.
   */
  details?: {
    [k: string]: ScalarValue | undefined;
  };
  /**
   * Last lines of a tool's stderr (e.g. FFmpeg), already redacted of user paths.
   */
  stderr_tail?: string;
  correlation_id?: CorrelationId;
}
/**
 * The proxy (preset proxy-h264-sdr): H.264 8-bit yuv420p, longer edge at most 1280 px, upright (rotation applied), source timing unless faster than 60 fps, AAC stereo, fast-start MP4.
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "ProxyInfo".
 */
export interface ProxyInfo {
  width: number;
  height: number;
  video_codec: "h264";
  pixel_format: "yuv420p";
  audio: boolean;
  duration_ms: number;
  /**
   * 'source': same timing as the source (VFR stays VFR); otherwise a constant rate cap.
   */
  frame_rate: string;
  tone_mapped: boolean;
  tone_map?: ToneMap;
}
/**
 * Thumbnails 0001.jpg ... in the artifact folder; thumbnail i (1-based) shows the asset at times_ms[i-1], the middle of its slice. 'count' equals the length of times_ms, which ascend (checked semantically).
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "FilmstripInfo".
 */
export interface FilmstripInfo {
  count: number;
  width: number;
  height: number;
  format: "jpeg";
  /**
   * @minItems 1
   * @maxItems 120
   */
  times_ms: [TimelineMs, ...TimelineMs[]];
  source: "proxy" | "original";
}
/**
 * Binary 'owm-waveform' v1: a 16-byte header (magic OWMW, version, buckets per second, sample rate, bucket count) and one (peak, rms) byte pair per bucket of the first audio stream mixed to mono.
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "WaveformInfo".
 */
export interface WaveformInfo {
  format: "owm-waveform";
  format_version: number;
  buckets_per_second: number;
  sample_rate_hz: number;
  bucket_count: number;
}
/**
 * Params of a 'proxy' job: prepare one asset's derived media. 'artifacts' defaults to all three; a filmstrip of an asset that needs a proxy also creates the proxy. 'force' regenerates even current artifacts.
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "DerivedMediaRequest".
 */
export interface DerivedMediaRequest {
  asset_id: AssetId;
  /**
   * @minItems 1
   * @maxItems 3
   */
  artifacts?: [DerivedKind] | [DerivedKind, DerivedKind] | [DerivedKind, DerivedKind, DerivedKind];
  proxy_policy?: ProxyPolicy;
  force?: boolean;
}
/**
 * Result of a 'proxy' job: what happened to each artifact it handled.
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "DerivedMediaResult".
 */
export interface DerivedMediaResult {
  asset_id: AssetId;
  proxy_decision: ProxyDecision;
  outcomes: {
    proxy?: DerivedOutcome;
    filmstrip?: DerivedOutcome;
    waveform?: DerivedOutcome;
  };
}
/**
 * What the derived-media cleanup removed. It only ever removes entries inside library/derived/ that no artifact row points at, and never follows links (a link is removed as a link and counted in skipped_links).
 *
 * This interface was referenced by `AssetDerivedMedia`'s JSON-Schema
 * via the `definition` "DerivedCleanupResult".
 */
export interface DerivedCleanupResult {
  removed_files: number;
  removed_dirs: number;
  freed_bytes: number;
  skipped_links: number;
}
/**
 * A time-ranged observation or suggestion about gameplay. Observations come from deterministic detectors or the user; suggestions come from models and stay suggestions until reviewed (spec 8.4.1, 8.4.6).
 */
export interface Event {
  schema_version: string;
  id: EventId;
  session_id: SessionId;
  asset_id?: AssetId;
  /**
   * Namespaced dotted event type, e.g. 'openworld.wanted_level_changed'.
   */
  type: string;
  start_ms: TimelineMs;
  end_ms: TimelineMs;
  confidence: Confidence;
  /**
   * Event-type-specific values. Open map of scalars.
   */
  attributes: {
    [k: string]: ScalarValue | undefined;
  };
  evidence: Evidence[];
  /**
   * Who produced the event. 'detector' and 'user' are observations; 'model' is a suggestion.
   */
  source: DetectorSource | ModelSource | UserSource;
  review_state: "unreviewed" | "confirmed" | "corrected" | "rejected";
}
/**
 * Template match inside a normalized frame region.
 */
export interface RegionTemplateEvidence {
  kind: "region_template";
  region: Region;
  score: Confidence;
  frame_ms?: TimelineMs1;
}
/**
 * Color or shape rule satisfied inside a region.
 */
export interface ColorRuleEvidence {
  kind: "color_rule";
  region: Region;
  score: Confidence;
}
/**
 * Text recognized inside a region, constrained to a vocabulary.
 */
export interface OcrEvidence {
  kind: "ocr";
  region: Region;
  text: string;
  score: Confidence;
}
/**
 * The state was observed consistently across this many frames.
 */
export interface TemporalConsistencyEvidence {
  kind: "temporal_consistency";
  frames: number;
  score: Confidence;
}
/**
 * Audio energy or spectral event in a time range.
 */
export interface AudioEvidence {
  kind: "audio";
  start_ms: TimelineMs;
  end_ms: TimelineMs;
  score: Confidence;
}
/**
 * Transcribed speech matching a phrase.
 */
export interface TranscriptEvidence {
  kind: "transcript";
  start_ms: TimelineMs;
  end_ms: TimelineMs;
  text: string;
  score: Confidence;
}
/**
 * A sampled frame a model looked at when proposing a suggestion.
 */
export interface ModelFrameEvidence {
  kind: "model_frame";
  frame_ms: TimelineMs;
  label: string;
  score: Confidence;
}
/**
 * Deterministic detector observation.
 *
 * This interface was referenced by `Event`'s JSON-Schema
 * via the `definition` "DetectorSource".
 */
export interface DetectorSource {
  kind: "detector";
  detector_id: Slug;
  detector_version: SemVer;
  profile_id?: Slug;
  profile_version?: SemVer;
  input_key?: Sha256;
  tool_versions?: {
    [k: string]: string | undefined;
  };
}
/**
 * Model suggestion. Must reference the sampled frames it is based on.
 *
 * This interface was referenced by `Event`'s JSON-Schema
 * via the `definition` "ModelSource".
 */
export interface ModelSource {
  kind: "model";
  model_id: string;
  prompt_version: SemVer;
  /**
   * @minItems 1
   */
  sampled_frames_ms: [TimelineMs, ...TimelineMs[]];
}
/**
 * Event created or marked manually by the user.
 *
 * This interface was referenced by `Event`'s JSON-Schema
 * via the `definition` "UserSource".
 */
export interface UserSource {
  kind: "user";
}
/**
 * Reproducibility record written next to an export (spec 8.9.3). Contains no footage, transcripts, or user paths.
 */
export interface ExportManifest {
  schema_version: string;
  created_at: UtcTimestamp;
  app_version: SemVer;
  project_id?: ProjectId;
  /**
   * @minItems 1
   */
  sources: [ManifestSource, ...ManifestSource[]];
  /**
   * Each 'source' is an index into 'sources' (checked semantically); out_ms > in_ms.
   *
   * @minItems 1
   */
  segments: [ManifestSegment, ...ManifestSegment[]];
  render: ManifestRender;
  detectors: ManifestDetector[];
  command?: ManifestCommand;
}
export interface ManifestSource {
  sha256: Sha256;
  original_name: string;
}
export interface ManifestSegment {
  source: number;
  in_ms: TimelineMs;
  out_ms: TimelineMs;
}
export interface ManifestRender {
  preset_id?: Slug;
  width: number;
  height: number;
  fps: Rational;
  layout: Slug;
}
/**
 * Exact rational number, used for frame rates (e.g. 30000/1001).
 */
export interface Rational {
  num: number;
  den: number;
}
export interface ManifestDetector {
  id: Slug;
  version: SemVer;
}
/**
 * Normalized description of the render command (spec 11.2). Paths are replaced with placeholders.
 */
export interface ManifestCommand {
  tool: "ffmpeg";
  tool_version: string;
  args: string[];
}
/**
 * Identity and similarity fingerprints of one asset (spec 8.1.4, M06). 'sha256' is exact identity. 'fast_hash' screens for exact duplicates cheaply. 'frames' and 'audio' cover bounded head and tail windows for duplicate candidates and overlap alignment (M12). Every fingerprint names its algorithm and version; rows written by an older version are stale and recomputed by the 'fingerprint' backfill job.
 */
export interface AssetFingerprints {
  schema_version: string;
  asset_id: AssetId;
  sha256: Sha256;
  fast_hash?: FastHash;
  frames?: FrameFingerprint;
  audio?: AudioFingerprint;
}
/**
 * 'owm-fast': SHA-256 over the file size (8 bytes, little-endian) and its first and last MiB. Equal values only suggest identical files; the full SHA-256 decides.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "FastHash".
 */
export interface FastHash {
  algorithm: "owm-fast";
  version: AlgorithmVersion;
  value: string;
  computed_at: UtcTimestamp;
}
/**
 * 'dhash256': difference hash of a 17x16 grayscale downscale, sampled at 'sample_fps' over the first and last 'window_ms' of the asset (the windows overlap for short assets).
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "FrameFingerprint".
 */
export interface FrameFingerprint {
  algorithm: "dhash256";
  version: AlgorithmVersion;
  sample_fps: number;
  window_ms: number;
  /**
   * @maxItems 1800
   */
  head: FrameHash[];
  /**
   * @maxItems 1800
   */
  tail: FrameHash[];
  computed_at: UtcTimestamp;
}
/**
 * One sampled frame: its time in the asset and a 256-bit perceptual hash (64 lowercase hex digits). 'flat' marks a near-uniform frame (black, white, fades) that carries no identity and is ignored when comparing.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "FrameHash".
 */
export interface FrameHash {
  t_ms: TimelineMs;
  hash: string;
  flat?: boolean;
}
/**
 * 'energy-envelope': loudness of the first audio stream, mixed to mono at 8 kHz, as one value per 1/'rate_hz' seconds (0 = silence, 255 = full scale; 0.5 dB steps over a 127.5 dB range) over the same windows as the frame fingerprint. Compact enough for cross-correlation when refining overlaps. Absent when the asset has no audio.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "AudioFingerprint".
 */
export interface AudioFingerprint {
  algorithm: "energy-envelope";
  version: AlgorithmVersion;
  rate_hz: number;
  window_ms: number;
  head_start_ms: TimelineMs;
  /**
   * @maxItems 3000
   */
  head: number[];
  tail_start_ms: TimelineMs;
  /**
   * @maxItems 3000
   */
  tail: number[];
  computed_at: UtcTimestamp;
}
/**
 * Two distinct assets whose sampled frames look the same (same content in another file: a remux, a re-encode, a re-download). Only ever reported: nothing is merged or deleted. A person decides with 'review_state'; an automatic recomputation never overrides that decision.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "DuplicateCandidate".
 */
export interface DuplicateCandidate {
  id: number;
  /**
   * The two assets, in ascending order.
   *
   * @minItems 2
   * @maxItems 2
   */
  asset_ids: [AssetId, AssetId];
  kind: "perceptual";
  score: Confidence;
  evidence: DuplicateEvidence;
  algorithm: "perceptual-match";
  version: AlgorithmVersion;
  review_state: "unreviewed" | "duplicate" | "distinct";
  created_at: UtcTimestamp;
  updated_at: UtcTimestamp;
}
/**
 * Why two assets are candidates: how many informative head/tail frame pairs were compared, how many matched (Hamming distance at most 'max_distance'), their mean distance, and the duration difference. 'audio_correlation' (-1..1) is added when both have audio; it informs review but does not decide.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "DuplicateEvidence".
 */
export interface DuplicateEvidence {
  compared_frames: number;
  matching_frames: number;
  mean_distance: number;
  max_distance: number;
  duration_delta_ms: number;
  audio_correlation?: number;
}
/**
 * Parameters of a 'fingerprint' (backfill) job. Without 'asset_ids', every asset is considered. Without 'force', only missing or stale (older-version) fingerprints are computed, so a restarted job continues where it stopped.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "FingerprintRequest".
 */
export interface FingerprintRequest {
  /**
   * @minItems 1
   * @maxItems 10000
   */
  asset_ids?: [AssetId, ...AssetId[]];
  force?: boolean;
}
/**
 * Result of a 'fingerprint' job.
 *
 * This interface was referenced by `AssetFingerprints`'s JSON-Schema
 * via the `definition` "FingerprintResult".
 */
export interface FingerprintResult {
  considered: number;
  /**
   * Assets that got at least one new fingerprint.
   */
  updated: number;
  up_to_date: number;
  /**
   * Assets whose bytes could not be read (missing source).
   */
  unavailable: number;
  /**
   * Assets whose fingerprinting failed (for example, undecodable frames).
   */
  failed: number;
  new_candidates: number;
}
/**
 * Per-file report of one import batch (spec 8.1, M05): the 'result' of an 'import' job. Every candidate file appears exactly once; failures are never dropped. Items name files only relative to the request root they came from; full paths stay in the job params and are never logged. Consistency between 'totals' and 'items' is checked semantically.
 */
export interface ImportResult {
  schema_version: string;
  mode: ImportMode;
  totals: ImportTotals;
  /**
   * @maxItems 10000
   */
  items: ImportItem[];
}
/**
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "ImportTotals".
 */
export interface ImportTotals {
  /**
   * Number of items.
   */
  files: number;
  imported: number;
  existing: number;
  relinked: number;
  skipped: number;
  failed: number;
}
/**
 * Outcome for one file. 'imported', 'existing' (same bytes already in the library), and 'relinked' (a missing asset found again) carry 'asset_id'; 'skipped' (not attempted: not a media file, or a link leaving the selected folder) and 'failed' carry 'error'.
 *
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "ImportItem".
 */
export interface ImportItem {
  /**
   * Index into the request's 'paths'.
   */
  source: number;
  /**
   * For files found in a folder: '/'-separated path relative to that folder. Absent when the request path was the file itself.
   */
  relative_path?: string;
  outcome: "imported" | "existing" | "relinked" | "skipped" | "failed";
  asset_id?: AssetId;
  error?: ErrorInfo;
  /**
   * Other assets that look like the same content (perceptual duplicate candidates, 1.4). Reported for review only; nothing is merged.
   *
   * @maxItems 20
   */
  candidate_asset_ids?:
    | []
    | [AssetId]
    | [AssetId, AssetId]
    | [AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId]
    | [AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId, AssetId]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ]
    | [
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId,
        AssetId
      ];
}
/**
 * Parameters of an 'import' job. Each path is a file or a folder; folders are scanned for media files ('recursive' includes subfolders). Paths must be absolute (checked by the worker).
 *
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "ImportRequest".
 */
export interface ImportRequest {
  /**
   * @minItems 1
   * @maxItems 100
   */
  paths: [string, ...string[]];
  mode: ImportMode;
  /**
   * Scan subfolders of folder paths. Default false.
   */
  recursive?: boolean;
  /**
   * Where the captures come from. Default 'other'.
   */
  source_kind?: "xbox" | "playstation" | "obs" | "capture_card" | "phone_upload" | "other";
}
/**
 * Parameters of a 'relink' job: point a referenced asset at a file in a new location. The file must be verified as the same content before the link changes.
 *
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "RelinkRequest".
 */
export interface RelinkRequest {
  asset_id: AssetId;
  path: string;
}
/**
 * Result of a 'relink' job. 'verified_by' names the identity check that matched; M05 compares size and the full SHA-256.
 *
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "RelinkResult".
 */
export interface RelinkResult {
  asset_id: AssetId;
  verified_by: "sha256";
}
/**
 * Result of a 'check_sources' job: which assets' original (reference) or library copy (managed) can no longer be found.
 *
 * This interface was referenced by `ImportResult`'s JSON-Schema
 * via the `definition` "SourceCheckResult".
 */
export interface SourceCheckResult {
  checked: number;
  /**
   * Assets missing after the check.
   */
  missing: number;
  newly_missing: number;
  /**
   * Assets marked missing before that were found again.
   */
  restored: number;
  /**
   * Up to 1000 missing assets, oldest first.
   *
   * @maxItems 1000
   */
  missing_asset_ids: AssetId[];
}
/**
 * Job change pushed by the worker over the /v1/jobs/events WebSocket. 'seq' increases by one for every event a worker process emits, so clients can detect gaps and resynchronize with GET /v1/jobs.
 */
export interface JobEvent {
  schema_version: string;
  seq: number;
  emitted_at: UtcTimestamp;
  /**
   * 'state' when the job's state changed, 'progress' for progress or message updates within a state.
   */
  kind: "state" | "progress";
  job: Job;
}
/**
 * Durable long-running work item (spec 9.5). Transitions are enforced by the job engine (M03), not by this schema. 'params' holds the handler input so interrupted jobs can be requeued; 'attempt' counts runs (1.1). 'idempotency_key' makes resubmission safe (1.3).
 */
export interface Job {
  schema_version: string;
  id: JobId;
  kind:
    | "import"
    | "analyze"
    | "proxy"
    | "transcribe"
    | "index"
    | "render"
    | "diagnostic"
    | "probe"
    | "relink"
    | "check_sources"
    | "fingerprint"
    | "group"
    | "align";
  state:
    | "queued"
    | "probing"
    | "fingerprinting"
    | "proxying"
    | "grouping"
    | "analyzing"
    | "transcribing"
    | "indexing"
    | "rendering"
    | "ready"
    | "cancelled"
    | "failed";
  /**
   * Handler input (JSON object). Must not contain secrets; paths are allowed but never logged.
   */
  params?: {};
  /**
   * Handler output (JSON object), set when the job reaches 'ready' (and on a failed 'import', so per-file errors stay visible). 'probe': MediaProbe (media-asset.schema.json#/$defs/MediaProbe); 'import': ImportResult (import.schema.json); 'relink': RelinkResult; 'check_sources': SourceCheckResult (import.schema.json#/$defs); 'fingerprint': FingerprintResult (fingerprint.schema.json#/$defs); 'proxy': DerivedMediaResult (derived-media.schema.json#/$defs); 'group': GroupResult (session.schema.json#/$defs); 'align': AlignResult (overlap.schema.json#/$defs). Must not contain secrets.
   */
  result?: {};
  /**
   * Client-chosen key (1.3). Submitting the same key again returns this job instead of creating a new one; reusing it for a different request is refused.
   */
  idempotency_key?: string;
  /**
   * 1 for the first run, incremented on each retry or requeue.
   */
  attempt?: number;
  /**
   * Measurable progress; done <= total (checked semantically).
   */
  progress?: {
    done: number;
    total: number;
  };
  message?: string;
  error?: ErrorInfo;
  correlation_id?: CorrelationId;
  created_at: UtcTimestamp;
  started_at?: UtcTimestamp;
  finished_at?: UtcTimestamp;
}
/**
 * Normalized metadata for one imported source file (spec 8.1.4, 8.2.4, 8.3.3). The source file itself is never modified. 'missing_at' is set when a referenced source can no longer be found.
 */
export interface MediaAsset {
  schema_version: string;
  id: AssetId;
  sha256: Sha256;
  /**
   * Partial-content hash for early duplicate screening (lowercase hex).
   */
  fast_hash?: string;
  original_name: string;
  source_kind: "xbox" | "playstation" | "obs" | "capture_card" | "phone_upload" | "other";
  import_mode: "reference" | "managed";
  capture_time?: CaptureTimeEstimate;
  duration_ms: DurationMs;
  /**
   * Size of the source file in bytes when it was imported (1.3). Used to notice a referenced file that was replaced.
   */
  size_bytes?: number;
  /**
   * FFprobe format name, e.g. 'mov,mp4,m4a,3gp,3g2,mj2'.
   */
  container: string;
  video?: VideoStream;
  audio?: AudioStream[];
  created_at: UtcTimestamp;
  missing_at?: UtcTimestamp;
}
/**
 * Estimated capture time and how it was derived.
 *
 * This interface was referenced by `MediaAsset`'s JSON-Schema
 * via the `definition` "CaptureTimeEstimate".
 */
export interface CaptureTimeEstimate {
  captured_at: UtcTimestamp;
  confidence: Confidence;
  /**
   * @minItems 1
   */
  basis: [
    "container_metadata" | "filename" | "filesystem_mtime" | "import_order" | "user",
    ...("container_metadata" | "filename" | "filesystem_mtime" | "import_order" | "user")[]
  ];
}
/**
 * This interface was referenced by `MediaAsset`'s JSON-Schema
 * via the `definition` "VideoStream".
 */
export interface VideoStream {
  codec: string;
  width: number;
  height: number;
  frame_rate: Rational1;
  pixel_format?: string;
  color: ColorInfo;
  average_frame_rate?: Rational2;
  /**
   * True when the container's base and average frame rates disagree by more than 0.1%. A header-level heuristic; frame timing is not decoded.
   */
  variable_frame_rate?: boolean;
  /**
   * Clockwise rotation in degrees to apply to the coded frame for upright display. 'width' and 'height' are coded (pre-rotation) dimensions.
   */
  rotation?: 0 | 90 | 180 | 270;
}
/**
 * Exact rational number, used for frame rates (e.g. 30000/1001).
 */
export interface Rational1 {
  num: number;
  den: number;
}
/**
 * FFprobe color metadata. 'hdr' is true for PQ (smpte2084) or HLG (arib-std-b67) transfer, or Dolby Vision. Unknown or unspecified values are omitted.
 *
 * This interface was referenced by `MediaAsset`'s JSON-Schema
 * via the `definition` "ColorInfo".
 */
export interface ColorInfo {
  primaries?: string;
  transfer?: string;
  matrix?: string;
  /**
   * 'tv' (limited) or 'pc' (full).
   */
  range?: string;
  hdr: boolean;
  mastering_display?: MasteringDisplay;
  content_light_level?: ContentLightLevel;
  dolby_vision?: DolbyVision;
}
/**
 * SMPTE ST 2086 mastering display luminance, in nits (cd/m²).
 */
export interface MasteringDisplay {
  min_luminance_nits?: number;
  max_luminance_nits?: number;
}
/**
 * CTA-861.3 content light level, in nits.
 */
export interface ContentLightLevel {
  max_cll: number;
  max_fall: number;
}
/**
 * Dolby Vision configuration record.
 */
export interface DolbyVision {
  profile: number;
  level?: number;
}
/**
 * Exact rational number, used for frame rates (e.g. 30000/1001).
 */
export interface Rational2 {
  num: number;
  den: number;
}
/**
 * This interface was referenced by `MediaAsset`'s JSON-Schema
 * via the `definition` "AudioStream".
 */
export interface AudioStream {
  codec: string;
  channels: number;
  sample_rate_hz: number;
  /**
   * FFmpeg channel layout name, e.g. 'stereo' or '5.1(side)'.
   */
  channel_layout?: string;
}
/**
 * Normalized FFprobe result for one source file (M04), before import assigns identity. Stored as the 'result' of a 'probe' job. Never contains the file path or free-form container tags.
 *
 * This interface was referenced by `MediaAsset`'s JSON-Schema
 * via the `definition` "MediaProbe".
 */
export interface MediaProbe {
  /**
   * FFprobe format name, e.g. 'mov,mp4,m4a,3gp,3g2,mj2'.
   */
  container: string;
  duration_ms: DurationMs;
  size_bytes: number;
  /**
   * Overall bit rate in bits per second, when known.
   */
  bit_rate?: number;
  creation_time?: UtcTimestamp1;
  video?: VideoStream;
  audio: AudioStream[];
  /**
   * Count of subtitle, data, attachment, and cover-art streams that were not normalized.
   */
  other_streams?: number;
  probed_with: ProbeTool;
}
export interface ProbeTool {
  ffprobe_version: string;
}
/**
 * Alignment of clip B after clip A in a session (spec 8.2.3, M12): whether B's start repeats A's end, where B starts inside A ('offset_ms'), how long the repeat is ('overlap_ms'), with confidence and evidence. 'applied' is what the session timeline uses: a user override, else a 'matched' result of the current algorithm version, else nothing. Low-confidence, ambiguous, stale, or missing results never shorten a clip.
 */
export interface AssetOverlap {
  schema_version: string;
  asset_a: AssetId;
  asset_b: AssetId;
  algorithm: "owm-overlap";
  version: number;
  /**
   * 'matched': overlap found and confident enough to apply. 'weak': found but below the apply threshold. 'ambiguous': the footage repeats at several offsets (menus, static scenes). 'no_match': no continuous match. 'insufficient': too few usable frames or no fingerprints. 'pending': not computed yet.
   */
  status: "matched" | "weak" | "ambiguous" | "no_match" | "insufficient" | "pending";
  /**
   * Computed by the current algorithm version. A stale result is never applied.
   */
  current: boolean;
  /**
   * Where B's time 0 falls in A (matched and weak results).
   */
  offset_ms?: number;
  overlap_ms?: TimelineMs2;
  confidence?: Confidence;
  /**
   * What the decision rests on: frame counts, votes per offset, matching frames, longest run, audio correlation, reason. Values are scalars or small arrays.
   */
  evidence: {};
  computed_at?: UtcTimestamp;
  /**
   * The user's overlap for this pair (0 means 'no overlap'). Always applied; recomputation never changes it.
   */
  override?: {
    overlap_ms: TimelineMs;
    set_at: UtcTimestamp;
  };
  applied: {
    overlap_ms: TimelineMs;
    source: "user" | "auto" | "none";
    confidence?: Confidence;
  };
}
/**
 * Params of an 'align' job: the sessions to align (default: all) and whether to recompute current results.
 *
 * This interface was referenced by `AssetOverlap`'s JSON-Schema
 * via the `definition` "AlignRequest".
 */
export interface AlignRequest {
  /**
   * @minItems 1
   * @maxItems 10000
   */
  session_ids?: [SessionId, ...SessionId[]];
  force?: boolean;
}
/**
 * Result of an 'align' job. Status counts cover computed and cached pairs.
 *
 * This interface was referenced by `AssetOverlap`'s JSON-Schema
 * via the `definition` "AlignResult".
 */
export interface AlignResult {
  pairs_considered: number;
  computed: number;
  cached: number;
  fingerprints_computed: number;
  sessions_updated: number;
  matched: number;
  weak: number;
  ambiguous: number;
  no_match: number;
  insufficient: number;
}
/**
 * Set the overlap between a clip and the clip before it (0 = no overlap), or clear the override with null.
 *
 * This interface was referenced by `AssetOverlap`'s JSON-Schema
 * via the `definition` "OverlapOverride".
 */
export interface OverlapOverride {
  overlap_ms: TimelineMs | null;
}
/**
 * Media-free local ROI overrides, separate from an installed profile.
 */
export interface ProfilePatch {
  schema_version: string;
  profile_id: Slug;
  base_version: SemVer;
  base_key: string;
  game_family: Slug;
  frame: ProfileFrame;
  regions: {
    [k: string]: Region | undefined;
  };
  provenance: {
    tool: "owm-calibration";
    version: "1";
    created_at: UtcTimestamp;
  };
}
export interface ProfileFrame {
  /**
   * @minItems 1
   */
  aspect_ratios: [string, ...string[]];
  min_width: number;
  min_height: number;
}
/**
 * Game/resolution/HUD/locale profile (spec 8.4.5). Holds normalized regions and detector settings only, never game assets. May be authored as YAML; it is validated as JSON.
 */
export interface Profile {
  schema_version: string;
  id: Slug;
  profile_version: SemVer;
  display_name: string;
  game_family: Slug;
  frame: ProfileFrame;
  /**
   * Named normalized regions. Names are slugs.
   */
  regions: {
    [k: string]: Region | undefined;
  };
  detectors: DetectorSettings[];
  safe_zones?: SafeZones;
  extends?: Slug;
  license?: string;
  capabilities?: "frames.gray"[];
  locales?: {
    [k: string]: LocalePack | undefined;
  };
}
/**
 * This interface was referenced by `Profile`'s JSON-Schema
 * via the `definition` "DetectorSettings".
 */
export interface DetectorSettings {
  id: Slug;
  enabled: boolean;
  min_confidence?: Confidence;
  confirmation_frames?: number;
  /**
   * BCP 47 language tag, e.g. 'en' or 'pt-BR'.
   */
  locale?: string;
  wanted?: WantedSettings;
}
/**
 * Analytic indicator row and temporal tuning. Compatibility must be evaluated separately.
 *
 * This interface was referenced by `Profile`'s JSON-Schema
 * via the `definition` "WantedSettings".
 */
export interface WantedSettings {
  max_level?: number;
  shape?: "star" | "disc";
  max_missing_frames?: number;
  debounce_ms?: number;
}
export interface SafeZones {
  /**
   * Region names that vertical layouts must keep visible. Each must be defined in 'regions' (checked semantically).
   */
  preserve: Slug[];
}
/**
 * This interface was referenced by `Profile`'s JSON-Schema
 * via the `definition` "LocalePack".
 */
export interface LocalePack {
  version: SemVer;
  license: string;
  vocabulary: {
    /**
     * @maxItems 256
     */
    [k: string]: string[] | undefined;
  };
}
/**
 * Non-destructive edit decision list (spec 11.1). References source assets by ID; never stores rendered media.
 */
export interface Project {
  schema_version: string;
  id: ProjectId;
  title: string;
  session_id?: SessionId;
  created_at: UtcTimestamp;
  updated_at: UtcTimestamp;
  tracks: VideoTrack[];
  captions: Caption[];
  overlays: BlurOverlay[];
  audio: AudioSettings;
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "VideoTrack".
 */
export interface VideoTrack {
  kind: "video";
  segments: Segment[];
}
/**
 * A source range placed on the timeline. source_out_ms > source_in_ms (checked semantically).
 *
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "Segment".
 */
export interface Segment {
  id: SegmentId;
  asset_id: AssetId;
  source_in_ms: TimelineMs;
  source_out_ms: TimelineMs;
  timeline_start_ms: TimelineMs;
  crop: Crop;
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "Crop".
 */
export interface Crop {
  mode: "fit" | "fill" | "safe" | "manual";
  keyframes: CropKeyframe[];
}
/**
 * Crop region at a segment-relative time.
 *
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "CropKeyframe".
 */
export interface CropKeyframe {
  at_ms: TimelineMs;
  region: Region;
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "Caption".
 */
export interface Caption {
  start_ms: TimelineMs;
  end_ms: TimelineMs;
  text: string;
}
/**
 * Privacy blur over a region for a time range.
 *
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "BlurOverlay".
 */
export interface BlurOverlay {
  kind: "blur";
  start_ms: TimelineMs;
  end_ms: TimelineMs;
  region: Region;
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "AudioSettings".
 */
export interface AudioSettings {
  gain_db: number;
  mute_ranges: TimeRange[];
}
/**
 * Inclusive start, exclusive end, in timeline milliseconds. end_ms >= start_ms (checked semantically).
 */
export interface TimeRange {
  start_ms: TimelineMs;
  end_ms: TimelineMs;
}
/**
 * Export preset (spec 11.4). Presets are JSON files so users can contribute new ones.
 */
export interface RenderPreset {
  schema_version: string;
  id: Slug;
  display_name: string;
  width: number;
  height: number;
  /**
   * 'source' keeps the source frame rate; otherwise an exact rational.
   */
  fps: "source" | Rational;
  video: VideoEncoding;
  audio: AudioEncoding;
  /**
   * Target size cap. Presets that set this must warn about quality loss in the UI.
   */
  max_file_size_mb?: number;
}
/**
 * Exactly one of crf or bitrate_kbps (checked semantically).
 */
export interface VideoEncoding {
  codec: "h264" | "hevc";
  crf?: number;
  bitrate_kbps?: number;
}
export interface AudioEncoding {
  codec: "aac";
  bitrate_kbps: number;
  sample_rate_hz: 44100 | 48000;
}
/**
 * A candidate play session (spec 8.2, M11): assets grouped by source, format, and capture-time gaps, in order, with the evidence for each join. 'review_state' says who owns it: 'unreviewed' sessions are rebuilt by the 'group' job; 'corrected' (changed by the user) and 'confirmed' sessions are never touched by automatic grouping.
 */
export interface Session {
  schema_version: string;
  id: SessionId;
  title: string;
  started_at?: UtcTimestamp2;
  ended_at?: UtcTimestamp3;
  /**
   * How sure the grouping is: the weakest join, or for one clip how sure its start time is. Null on corrected sessions. See docs/architecture/sessions.md.
   */
  grouping_confidence?: Confidence | null;
  review_state: "unreviewed" | "confirmed" | "corrected";
  /**
   * Members in session order: order_index is 0, 1, 2, … and session_start_ms never decreases (checked semantically).
   *
   * @minItems 1
   */
  assets: [SessionMember, ...SessionMember[]];
  grouping?: SessionGrouping | null;
  created_at: UtcTimestamp;
  updated_at?: UtcTimestamp;
}
/**
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "SessionMember".
 */
export interface SessionMember {
  asset_id: AssetId;
  order_index: number;
  session_start_ms: TimelineMs3;
  duration_ms: TimelineMs;
  capture_time?: CaptureTimeEstimate;
  overlap_with_previous_ms?: TimelineMs4;
  alignment_confidence?: Confidence1;
}
/**
 * How an automatic session was formed. Null on corrected sessions: their membership is the user's decision (see the correction log).
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "SessionGrouping".
 */
export interface SessionGrouping {
  algorithm: "owm-metadata-gap";
  version: number;
  settings: {
    max_gap_ms: number;
  };
  links: GroupingLink[];
  /**
   * Why the first clip did not join the previous clip from the same source.
   */
  split_before?: GroupingReason[];
  /**
   * Capture-time caveats of the members (time-zone mismatch, copy times, …).
   *
   * @maxItems 50
   */
  notes?: string[];
}
/**
 * Why to_asset_id continues from_asset_id (adjacent members). gap_ms is negative when the clips overlap.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "GroupingLink".
 */
export interface GroupingLink {
  from_asset_id: AssetId;
  to_asset_id: AssetId;
  gap_ms: number;
  confidence: Confidence;
  /**
   * @minItems 1
   */
  reasons: [GroupingReason, ...GroupingReason[]];
}
/**
 * Params of a 'group' job. max_gap_ms defaults to the 'sessions.max_gap_ms' setting, else 15 minutes.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "GroupRequest".
 */
export interface GroupRequest {
  max_gap_ms?: number;
}
/**
 * Result of a 'group' job. A second run over unchanged assets creates, updates, and removes nothing.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "GroupResult".
 */
export interface GroupResult {
  considered_assets: number;
  /**
   * Assets in corrected or confirmed sessions, left as they are.
   */
  locked_assets: number;
  capture_times_updated: number;
  sessions_created: number;
  sessions_updated: number;
  sessions_unchanged: number;
  sessions_removed: number;
}
/**
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "MergeRequest".
 */
export interface MergeRequest {
  /**
   * @minItems 2
   * @maxItems 50
   */
  session_ids: [SessionId, SessionId, ...SessionId[]];
}
/**
 * Split after this member: it and the clips before it stay; the rest form a new session.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "SplitRequest".
 */
export interface SplitRequest {
  after_asset_id: AssetId;
}
/**
 * Every member exactly once, in the new order.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "ReorderRequest".
 */
export interface ReorderRequest {
  /**
   * @minItems 1
   */
  asset_ids: [AssetId, ...AssetId[]];
}
/**
 * Mark a member as unrelated: it moves to a session of its own that automatic grouping never changes.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "RemoveRequest".
 */
export interface RemoveRequest {
  asset_id: AssetId;
}
/**
 * One entry of the correction log.
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "SessionCorrection".
 */
export interface SessionCorrection {
  id: number;
  kind: "merge" | "split" | "reorder" | "remove" | "confirm" | "overlap";
  session_ids: SessionId[];
  asset_ids: AssetId[];
  detail?: {
    [k: string]: ScalarValue | undefined;
  } | null;
  created_at: UtcTimestamp;
}
/**
 * A user-approved folder whose completed video files are imported automatically (spec 6.1, 8.1.2, M07). The desktop host watches it and reports stable files; the worker decides whether to import. Nothing in a watched folder is ever moved, renamed, or deleted.
 */
export interface WatchedFolder {
  schema_version: string;
  id: number;
  /**
   * Absolute path of the folder. Local data: never logged.
   */
  path: string;
  source_kind: SourceKind;
  /**
   * Import mode for files found here.
   */
  mode: "reference" | "managed";
  recursive: boolean;
  include: Patterns;
  exclude: Patterns;
  /**
   * Disabled folders are not watched, scanned, or imported from.
   */
  enabled: boolean;
  created_at: UtcTimestamp;
  updated_at: UtcTimestamp;
  last_scan_at?: UtcTimestamp4;
  /**
   * Reported by the host: whether the folder could be read at the last check.
   */
  availability?: "unknown" | "available" | "unavailable";
  last_error?: ErrorInfo2;
  stats: WatchedFolderStats;
}
/**
 * Machine-readable error shared by the worker API, jobs, and the desktop host. Embedded in other documents, so it has no schema_version of its own.
 */
export interface ErrorInfo2 {
  /**
   * Stable dotted snake_case code, e.g. 'media.probe_failed'. Never localized.
   */
  code: string;
  /**
   * Human-readable explanation. Must not contain media contents or transcripts.
   */
  message: string;
  retryable: boolean;
  /**
   * Extra machine-readable context. Values are scalars only.
   */
  details?: {
    [k: string]: ScalarValue | undefined;
  };
  /**
   * Last lines of a tool's stderr (e.g. FFmpeg), already redacted of user paths.
   */
  stderr_tail?: string;
  correlation_id?: CorrelationId;
}
/**
 * Files the worker has seen in this folder, by the state of their latest import.
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "WatchedFolderStats".
 */
export interface WatchedFolderStats {
  tracked: number;
  imported: number;
  in_progress: number;
  failed: number;
}
/**
 * Create (POST, 'path' required) or change (PATCH, 'path' not allowed) a watched folder. Omitted fields keep their current value or default: source_kind 'other', mode 'reference', recursive true, the default include/exclude patterns, enabled true.
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "WatchedFolderRequest".
 */
export interface WatchedFolderRequest {
  path?: string;
  source_kind?: SourceKind;
  mode?: "reference" | "managed";
  recursive?: boolean;
  include?: Patterns;
  exclude?: Patterns;
  enabled?: boolean;
}
/**
 * Sent by the host for a file whose size and modification time stayed unchanged for the stabilization period and that could be opened for reading.
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "WatchedFileReport".
 */
export interface WatchedFileReport {
  relative_path: string;
  size_bytes: number;
  mtime_ns: number;
}
/**
 * The worker's answer to a report. 'queued': an import job was submitted. 'known': this exact version (path, size, mtime) was already imported or found unimportable. 'in_progress': its import is still running. 'backoff': its last import failed with a retryable error and 'retry_at' has not passed. 'ignored': the file does not match the folder's patterns.
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "WatchedFileDecision".
 */
export interface WatchedFileDecision {
  action: "queued" | "known" | "in_progress" | "backoff" | "ignored";
  job_id?: JobId;
  retry_at?: UtcTimestamp;
}
/**
 * The worker's record of one file in a watched folder (its latest version).
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "WatchedFile".
 */
export interface WatchedFile {
  relative_path: string;
  size_bytes: number;
  mtime_ns: number;
  state: "queued" | "in_progress" | "imported" | "failed";
  attempts: number;
  job_id?: JobId;
  asset_id?: AssetId;
  error?: ErrorInfo;
  retry_at?: UtcTimestamp;
  updated_at: UtcTimestamp;
}
/**
 * Sent by the host after each availability check or reconciliation scan.
 *
 * This interface was referenced by `WatchedFolder`'s JSON-Schema
 * via the `definition` "ScanReport".
 */
export interface ScanReport {
  available: boolean;
  /**
   * True when a full reconciliation scan finished (sets last_scan_at).
   */
  scanned?: boolean;
  error?: ErrorInfo;
}
