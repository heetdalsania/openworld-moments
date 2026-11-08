// SPDX-License-Identifier: AGPL-3.0-or-later
// Typed client for the worker API. Requests go through the host's `worker_api` command,
// which only forwards allow-listed routes; the worker token never reaches the UI.
import { invoke } from "@tauri-apps/api/core";
import type {
  EventReview,
  EventReviewItem,
  AssetDerivedMedia,
  AssetOverlap,
  ImportResult,
  Job,
  MediaAsset,
  Session,
  SpeechModels,
  Transcript,
} from "@openworld-moments/contracts";

/** A contract ErrorInfo, or a stand-in for transport failures. */
export interface ApiError {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
}

export function toApiError(error: unknown): ApiError {
  if (error && typeof error === "object" && "message" in error) {
    const e = error as Partial<ApiError>;
    return {
      code: typeof e.code === "string" ? e.code : "app.error",
      message: String(e.message),
      retryable: Boolean(e.retryable),
      ...(e.details ? { details: e.details } : {}),
    };
  }
  return { code: "app.error", message: String(error), retryable: true };
}

/** Plain-language explanations for codes users meet often. Falls back to the message. */
const EXPLAIN: Record<string, string> = {
  "worker.unavailable": "The media worker is not running. It restarts automatically.",
  "worker.not_bundled": "This build has no media worker configured.",
  "media.source_missing": "The original file is missing, offline, or changed since import.",
  "derived.source_unavailable": "The original file cannot be read right now.",
  "derived.disk_full": "There is not enough free space in the library folder.",
  "derived.ffmpeg_incapable": "Your FFmpeg build lacks a component needed to prepare playback.",
  "tool.ffmpeg_missing": "FFmpeg is not installed. Install FFmpeg 6.0 or newer.",
  "tool.ffprobe_missing": "FFprobe is not installed. Install FFmpeg 6.0 or newer.",
  "import.unsupported": "This file type is not supported.",
  "media.damaged": "The file is damaged or incomplete.",
};

export function describeError(error: ApiError): string {
  return EXPLAIN[error.code] ?? error.message;
}

async function call<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  try {
    return await invoke<T>("worker_api", { method, path, body: body ?? null });
  } catch (error) {
    throw toApiError(error);
  }
}

export const PAGE_SIZE = 60;

export function listAssets(after?: string): Promise<MediaAsset[]> {
  const query = new URLSearchParams({ order: "newest", limit: String(PAGE_SIZE) });
  if (after) query.set("after", after);
  return call("GET", `/v1/assets?${query.toString()}`);
}

export function getAsset(id: string): Promise<MediaAsset> {
  return call("GET", `/v1/assets/${id}`);
}

export function getDerived(id: string): Promise<AssetDerivedMedia> {
  return call("GET", `/v1/assets/${id}/derived`);
}

export interface DerivedOptions {
  force?: boolean;
  proxy_policy?: "auto" | "always";
  idempotency_key?: string;
}

export function prepareDerived(id: string, options: DerivedOptions = {}): Promise<Job> {
  return call("POST", `/v1/assets/${id}/derived`, options);
}

export type ImportMode = "reference" | "managed";

export function startImport(paths: string[], mode: ImportMode): Promise<Job> {
  return call("POST", "/v1/imports", { paths, mode, recursive: true });
}

export function listJobs(): Promise<Job[]> {
  return call("GET", "/v1/jobs?limit=200");
}

export function cancelJob(id: string): Promise<Job> {
  return call("POST", `/v1/jobs/${id}/cancel`);
}

export function retryJob(id: string): Promise<Job> {
  return call("POST", `/v1/jobs/${id}/retry`);
}

// -- sessions (M11-M13) ---------------------------------------------------------------

export function listSessions(): Promise<Session[]> {
  return call("GET", "/v1/sessions?limit=200");
}

export function getSession(id: string): Promise<Session> {
  return call("GET", `/v1/sessions/${id}`);
}

export function sessionOverlaps(id: string): Promise<AssetOverlap[]> {
  return call("GET", `/v1/sessions/${id}/overlaps`);
}

export function recomputeSessions(): Promise<Job> {
  return call("POST", "/v1/sessions/recompute", {});
}

export function alignSessions(sessionIds?: string[]): Promise<Job> {
  return call("POST", "/v1/sessions/align", sessionIds ? { session_ids: sessionIds } : {});
}

export function mergeSessions(sessionIds: string[]): Promise<Session> {
  return call("POST", "/v1/sessions/merge", { session_ids: sessionIds });
}

export function splitSession(id: string, afterAssetId: string): Promise<Session[]> {
  return call("POST", `/v1/sessions/${id}/split`, { after_asset_id: afterAssetId });
}

export function reorderSession(id: string, assetIds: string[]): Promise<Session> {
  return call("POST", `/v1/sessions/${id}/order`, { asset_ids: assetIds });
}

export function removeFromSession(id: string, assetId: string): Promise<Session[]> {
  return call("POST", `/v1/sessions/${id}/remove`, { asset_id: assetId });
}

export function confirmSession(id: string): Promise<Session> {
  return call("POST", `/v1/sessions/${id}/confirm`);
}

/** Set the overlap before `assetId` (0 = no overlap) or clear the override (null). */
export function setOverlap(
  id: string,
  assetId: string,
  overlapMs: number | null,
): Promise<Session> {
  return call("PUT", `/v1/sessions/${id}/overlaps/${assetId}`, { overlap_ms: overlapMs });
}

// -- transcription (M18) -------------------------------------------------------------

/** Engine availability, explicitly installed models, and the manual-install catalog. */
export function speechModels(): Promise<SpeechModels> {
  return call("GET", "/v1/transcription/models");
}

export interface TranscribeOptions {
  model: string;
  language?: string;
  force?: boolean;
}

export function transcribeSession(id: string, options: TranscribeOptions): Promise<Job> {
  return call("POST", `/v1/sessions/${id}/transcribe`, options);
}

export function getTranscript(id: string): Promise<Transcript> {
  return call("GET", `/v1/sessions/${id}/transcript`);
}

/** Deletes derived transcript text only; media is never touched. */
export function deleteTranscript(id: string): Promise<{ deleted_segments: number }> {
  return call("DELETE", `/v1/sessions/${id}/transcript`);
}

export type {
  AssetDerivedMedia,
  AssetOverlap,
  ImportResult,
  Job,
  MediaAsset,
  Session,
  SpeechModels,
  Transcript,
};

// -- calibration (M15) ---------------------------------------------------------------
export interface CalibrationState {
  base: import("@openworld-moments/contracts").Profile;
  base_key: string;
  effective: import("@openworld-moments/contracts").Profile;
  patch: import("@openworld-moments/contracts").ProfilePatch | null;
  base_changed: boolean;
  conflict: string | null;
}
export interface ProfileSummary {
  id: string;
  display_name: string;
  profile_version: string;
}
export const listProfiles = (): Promise<ProfileSummary[]> => call("GET", "/v1/profiles");
export const getCalibration = (id: string): Promise<CalibrationState> =>
  call("GET", `/v1/profiles/${id}/calibration`);
export const saveCalibration = (
  id: string,
  baseKey: string,
  regions: object,
): Promise<CalibrationState> =>
  call("PUT", `/v1/profiles/${id}/calibration`, { base_key: baseKey, regions });
export const importProfilePatch = (id: string, patch: unknown): Promise<CalibrationState> =>
  call("POST", `/v1/profiles/${id}/patch`, patch);
export const resetCalibration = (id: string): Promise<CalibrationState> =>
  call("POST", `/v1/profiles/${id}/reset`);
export const exportProfilePatch = (id: string): Promise<boolean> =>
  invoke("calibration_export_patch", { profileId: id });
export const exportCropSample = (data: number[]): Promise<boolean> =>
  invoke("calibration_export_sample", { data });
export interface DetectorPreview {
  available: boolean;
  message?: string;
  detector_id?: string;
  detector_version?: string;
  sample_count?: number;
  confirmation_frames?: number;
  detections?: { type: string; start_ms: number; end_ms: number; confidence: number }[];
}
export const previewCalibration = (
  id: string,
  baseKey: string,
  regions: object,
  gray: number[],
  sourceMs: number,
): Promise<DetectorPreview> =>
  call("POST", `/v1/profiles/${id}/preview`, {
    base_key: baseKey,
    regions,
    gray,
    source_ms: sourceMs,
  });

// -- event review (M19) --------------------------------------------------------------
export function eventReview(id: string, offset = 0): Promise<EventReview> {
  return call("GET", `/v1/sessions/${id}/review?offset=${offset}&limit=50`);
}
export interface EventReviewChange {
  layout_key: string;
  expected_revision: number;
  action: "approve" | "reject" | "correct" | "reset";
  type?: string;
  start_ms?: number;
  end_ms?: number;
}
export function reviewEvent(
  id: string,
  eventId: string,
  change: EventReviewChange,
): Promise<EventReviewItem> {
  return call("POST", `/v1/sessions/${id}/review/${eventId}`, change);
}
export function addManualEvent(
  id: string,
  event: { layout_key: string; type: string; start_ms: number; end_ms: number },
): Promise<EventReviewItem> {
  return call("POST", `/v1/sessions/${id}/review`, event);
}
export function analyzeSession(id: string, profileId: string): Promise<Job> {
  return call("POST", `/v1/sessions/${id}/analyze`, { profile_id: profileId, force: true });
}
export type { EventReview, EventReviewItem };

// -- editor document persistence (M21; visual editor follows in M22) --------------------
export interface ProjectState {
  document: import("@openworld-moments/contracts").EditorProject;
  revision: number;
  recovery: import("@openworld-moments/contracts").EditorProject | null;
  sources?: { asset_id: string; state: "missing" | "mismatch" | "available_unverified" }[];
}
export const getProject = (id: string): Promise<ProjectState> => call("GET", `/v1/projects/${id}`);
export const saveProject = (
  document: ProjectState["document"],
  expectedRevision: number,
): Promise<ProjectState> =>
  call("PUT", `/v1/projects/${document.project.id}`, {
    document,
    expected_revision: expectedRevision,
  });
export const createProject = (
  sessionId: string,
  selection: { title: string; layout_key: string; start_ms: number; end_ms: number },
): Promise<ProjectState> => call("POST", `/v1/sessions/${sessionId}/projects`, selection);
export const exportProject = (id: string): Promise<ProjectState["document"]> =>
  call("GET", `/v1/projects/${id}/portable`);
export const importProject = (
  document: ProjectState["document"],
  bindings: Record<string, string> = {},
  confirmReplacements: string[] = [],
): Promise<ProjectState> =>
  call("POST", "/v1/projects/import", {
    document,
    bindings,
    confirm_replacements: confirmReplacements,
  });

export const relinkProject = (
  id: string,
  expectedRevision: number,
  bindings: Record<string, string>,
  confirmReplacements: string[] = [],
): Promise<ProjectState> =>
  call("POST", `/v1/projects/${id}/relink`, {
    expected_revision: expectedRevision,
    bindings,
    confirm_replacements: confirmReplacements,
  });

export interface ProjectPage {
  items: {
    id: string;
    title: string;
    session_id: string | null;
    updated_at: string;
    revision: number;
  }[];
  total: number;
  offset: number;
}
export const listProjects = (offset = 0): Promise<ProjectPage> =>
  call("GET", `/v1/projects?offset=${offset}&limit=50`);
export const projectSelection = (
  id: string,
): Promise<{ layout_key: string; duration_ms: number }> =>
  call("GET", `/v1/sessions/${id}/project-selection`);

/** Explicit native save dialog; no webview-supplied destination path. */
export const exportCaptions = (text: string, format: "srt" | "vtt"): Promise<boolean> =>
  invoke("caption_export", { text, format });

// -- rendering (M24) -------------------------------------------------------------------
export type RenderPreset = import("@openworld-moments/contracts").RenderPreset;
export type RenderRecord = import("@openworld-moments/contracts").RenderRecord;
export type RenderEncoders = import("@openworld-moments/contracts").RenderEncoders;

export interface RenderOptions {
  preset_id: string;
  encoder?: string;
  omit_text?: boolean;
  review_layout?: boolean;
  expected_revision?: number;
}

export const renderPresets = (): Promise<RenderPreset[]> => call("GET", "/v1/render/presets");

/** Encoders that passed a real test encode with this FFmpeg; others carry a reason. */
export const renderEncoders = (): Promise<RenderEncoders> => call("GET", "/v1/render/encoders");

/** Renders the project's last saved revision into the library. */
export const renderProject = (id: string, options: RenderOptions): Promise<Job> =>
  call("POST", `/v1/projects/${id}/render`, options);

export const projectRenders = (id: string): Promise<RenderRecord[]> =>
  call("GET", `/v1/projects/${id}/renders`);

// -- search and collections (M26) ------------------------------------------------------

export type SearchResults = import("@openworld-moments/contracts").SearchResults;
export type SearchResult = import("@openworld-moments/contracts").SearchResult;
export type SearchFilters = import("@openworld-moments/contracts").SearchFilters;
export type SearchRequest = import("@openworld-moments/contracts").SearchRequest;
export type SearchIndexStatus = import("@openworld-moments/contracts").SearchIndexStatus;
export type Collection = import("@openworld-moments/contracts").Collection;
export type CollectionSummary = import("@openworld-moments/contracts").CollectionSummary;
export type CollectionRule = import("@openworld-moments/contracts").CollectionRule;
export type CollectionItemRef = import("@openworld-moments/contracts").CollectionItemRef;

export const search = (request: SearchRequest): Promise<SearchResults> =>
  call("POST", "/v1/search", request);

export const searchIndexStatus = (check = false): Promise<SearchIndexStatus> =>
  call("GET", check ? "/v1/search/index?check=true" : "/v1/search/index");

/** Rebuilds the derived index from canonical records in a background job. */
export const rebuildSearchIndex = (): Promise<Job> => call("POST", "/v1/search/index/rebuild", {});

/** Deletes all derived search text; clips, events and transcripts are untouched. */
export const clearSearchIndex = (): Promise<SearchIndexStatus> =>
  call("DELETE", "/v1/search/index");

export const listCollections = (): Promise<CollectionSummary[]> => call("GET", "/v1/collections");

export const getCollection = (id: string, offset = 0, limit = 50): Promise<Collection> =>
  call(
    "GET",
    offset ? `/v1/collections/${id}?offset=${offset}&limit=${limit}` : `/v1/collections/${id}`,
  );

export const createCollection = (name: string, rule?: CollectionRule): Promise<CollectionSummary> =>
  call("POST", "/v1/collections", rule ? { name, rule } : { name });

export const renameCollection = (id: string, name: string): Promise<CollectionSummary> =>
  call("PUT", `/v1/collections/${id}`, { name });

export const deleteCollection = (id: string): Promise<{ deleted: boolean }> =>
  call("DELETE", `/v1/collections/${id}`);

export const addToCollection = (
  id: string,
  item: CollectionItemRef,
): Promise<{ item_id: number; added: boolean }> =>
  call("POST", `/v1/collections/${id}/items`, item);

export const removeFromCollection = (id: string, itemId: number): Promise<{ deleted: boolean }> =>
  call("DELETE", `/v1/collections/${id}/items/${itemId}`);
