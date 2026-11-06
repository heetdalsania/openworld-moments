// SPDX-License-Identifier: Apache-2.0
// GENERATED FILE. Do not edit by hand.
// Source: packages/contracts/schemas/*.schema.json
// Regenerate with: pnpm contracts:generate

/**
 * Primitive value allowed in open attribute maps.
 */
export type ScalarValue = string | number | boolean | null;
/**
 * Opaque request/log correlation ID: 'cor_' + ULID.
 */
export type CorrelationId = string;
/**
 * Opaque event ID: 'evt_' + ULID.
 */
export type EventId = string;
/**
 * Opaque session ID: 'ses_' + ULID.
 */
export type SessionId = string;
/**
 * Opaque media asset ID: 'ast_' + ULID.
 */
export type AssetId = string;
/**
 * Position on a media or session timeline in integer milliseconds from its start.
 */
export type TimelineMs = number;
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
 * Lowercase identifier for profiles, presets, detectors, and regions.
 */
export type Slug = string;
/**
 * Semantic version without build metadata, e.g. '0.3.0' or '1.2.0-beta.1'.
 */
export type SemVer = string;
/**
 * RFC 3339 timestamp in UTC with a literal 'Z' suffix and at most millisecond precision.
 */
export type UtcTimestamp = string;
/**
 * Opaque project ID: 'prj_' + ULID.
 */
export type ProjectId = string;
/**
 * Lowercase hex SHA-256 digest.
 */
export type Sha256 = string;
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
 * Opaque timeline segment ID: 'seg_' + ULID.
 */
export type SegmentId = string;

export interface ContractsBundle {
  error?: ErrorInfo;
  event?: Event;
  evidence?: Evidence;
  "export-manifest"?: ExportManifest;
  "job-event"?: JobEvent;
  job?: Job;
  "media-asset"?: MediaAsset;
  profile?: Profile;
  project?: Project;
  "render-preset"?: RenderPreset;
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
 * Durable long-running work item (spec 9.5). Transitions are enforced by the job engine (M03), not by this schema. 'params' holds the handler input so interrupted jobs can be requeued; 'attempt' counts runs (1.1).
 */
export interface Job {
  schema_version: string;
  id: JobId;
  kind: "import" | "analyze" | "proxy" | "transcribe" | "index" | "render" | "diagnostic" | "probe";
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
   * Handler output (JSON object), set when the job reaches 'ready'. For 'probe' jobs: a MediaProbe (media-asset.schema.json#/$defs/MediaProbe). Must not contain secrets.
   */
  result?: {};
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
}
export interface SafeZones {
  /**
   * Region names that vertical layouts must keep visible. Each must be defined in 'regions' (checked semantically).
   */
  preserve: Slug[];
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
