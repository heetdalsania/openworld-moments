// SPDX-License-Identifier: AGPL-3.0-or-later
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type { WatchedFile, WatchedFolder } from "@openworld-moments/contracts";

/** Mirrors `FolderStatus` in src-tauri/src/watch/service.rs. */
export interface FolderStatus {
  id: number;
  state: "starting" | "watching" | "scanning-only" | "unavailable";
  pending: number;
  cloud_only: number;
  reported: number;
  rejected: number;
  next_check_ms: number | null;
}

export interface WatchedFolderView {
  folder: WatchedFolder;
  status: FolderStatus | undefined;
}

export type SourceKind = WatchedFolder["source_kind"];

/** An ErrorInfo-shaped rejection from a host command, as plain text. */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

export async function listWatched(): Promise<WatchedFolderView[]> {
  const result = await invoke<{ folders: WatchedFolder[]; status: FolderStatus[] }>(
    "watched_folders_list",
  );
  const byId = new Map(result.status.map((s) => [s.id, s]));
  return result.folders.map((folder) => ({ folder, status: byId.get(folder.id) }));
}

export function addWatched(path: string, sourceKind: SourceKind): Promise<WatchedFolder> {
  return invoke<WatchedFolder>("watched_folder_add", { path, sourceKind });
}

export function updateWatched(
  id: number,
  changes: Partial<Pick<WatchedFolder, "enabled" | "recursive" | "include" | "exclude">>,
): Promise<WatchedFolder> {
  return invoke<WatchedFolder>("watched_folder_update", { id, changes });
}

export async function removeWatched(id: number): Promise<void> {
  await invoke("watched_folder_remove", { id });
}

export function watchedFiles(id: number): Promise<WatchedFile[]> {
  return invoke<WatchedFile[]>("watched_folder_files", { id });
}

/** Native folder picker. Resolves to null when the user cancels. */
export async function pickFolder(title: string): Promise<string | null> {
  const choice = await open({ directory: true, multiple: false, title });
  return typeof choice === "string" ? choice : null;
}

/** One line describing what the watcher is doing for a folder. */
export function describeFolder(view: WatchedFolderView): string {
  const { folder, status } = view;
  if (!folder.enabled) return "Paused — not watched";
  if (status?.state === "unavailable" || folder.availability === "unavailable") {
    const retry = status?.next_check_ms ?? null;
    const when = retry === null ? "" : ` Checking again in ${Math.ceil(retry / 1000)} s.`;
    return `Unavailable — the folder cannot be read right now.${when}`;
  }
  const parts: string[] = [];
  if (status?.state === "starting" || status === undefined) parts.push("Starting…");
  if (status?.state === "watching") parts.push("Watching");
  if (status?.state === "scanning-only") parts.push("Watching (periodic scans only)");
  const { imported, in_progress, failed } = folder.stats;
  parts.push(`${imported} imported`);
  if (in_progress) parts.push(`${in_progress} importing`);
  if (status?.pending) parts.push(`${status.pending} waiting for files to finish copying`);
  if (status?.cloud_only) parts.push(`${status.cloud_only} still in the cloud`);
  if (failed) parts.push(`${failed} failed`);
  return parts.join(" · ");
}

/** Split a comma- or newline-separated pattern list typed by the user. */
export function parsePatterns(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}
