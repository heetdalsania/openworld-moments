// SPDX-License-Identifier: AGPL-3.0-or-later
// Typed client for the worker API. Requests go through the host's `worker_api` command,
// which only forwards allow-listed routes; the worker token never reaches the UI.
import { invoke } from "@tauri-apps/api/core";
import type {
  AssetDerivedMedia,
  ImportResult,
  Job,
  MediaAsset,
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

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
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

export type { AssetDerivedMedia, ImportResult, Job, MediaAsset };
