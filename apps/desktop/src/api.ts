// SPDX-License-Identifier: AGPL-3.0-or-later
// Typed client for the worker API. Requests go through the host's `worker_api` command,
// which only forwards allow-listed routes; the worker token never reaches the UI.
import { invoke } from "@tauri-apps/api/core";
import type {
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
