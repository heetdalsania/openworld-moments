// SPDX-License-Identifier: AGPL-3.0-or-later
// Durable job state for the job center. The worker's job list is the truth: it is
// loaded at start, after a UI reload, after a worker restart, and whenever the host
// reports missed events; live events update it in between.
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { useEffect, useSyncExternalStore } from "react";
import { type ApiError, type Job, listJobs, toApiError } from "./api";
import { invalidate } from "./query";

export const JOB_EVENT = "worker://job-event";
export const RESYNC_EVENT = "worker://resync";
export const STATUS_EVENT = "worker://status";

export const ACTIVE_STATES = new Set([
  "queued",
  "probing",
  "fingerprinting",
  "proxying",
  "grouping",
  "analyzing",
  "transcribing",
  "indexing",
  "rendering",
]);

const LABELS: Record<string, string> = {
  import: "Import",
  proxy: "Prepare playback",
  fingerprint: "Fingerprint library",
  probe: "Read media details",
  relink: "Relink file",
  check_sources: "Check original files",
  group: "Group sessions",
  align: "Find repeated footage",
  analyze: "Analyze session",
  story: "Suggest stories",
  transcribe: "Transcribe speech",
  render: "Render video",
  index: "Rebuild search index",
  diagnostic: "Diagnostic",
};

export function jobLabel(job: Job): string {
  return LABELS[job.kind] ?? job.kind;
}

const STATE_LABELS: Record<string, string> = {
  queued: "Waiting",
  probing: "Reading media",
  fingerprinting: "Fingerprinting",
  proxying: "Preparing playback",
  grouping: "Grouping",
  analyzing: "Working",
  transcribing: "Transcribing",
  indexing: "Indexing",
  rendering: "Rendering",
  ready: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function stateLabel(job: Job): string {
  return STATE_LABELS[job.state] ?? job.state;
}

export function isActive(job: Job): boolean {
  return ACTIVE_STATES.has(job.state);
}

interface JobsState {
  jobs: Job[];
  loaded: boolean;
  error: ApiError | undefined;
}

let state: JobsState = { jobs: [], loaded: false, error: undefined };
const listeners = new Set<() => void>();

function set(next: Partial<JobsState>): void {
  state = { ...state, ...next };
  for (const listener of listeners) listener();
}

function sorted(jobs: Iterable<Job>): Job[] {
  return [...jobs].sort((a, b) =>
    a.created_at === b.created_at
      ? b.id.localeCompare(a.id)
      : b.created_at.localeCompare(a.created_at),
  );
}

/** Replace the list with the worker's durable view. */
export async function reloadJobs(): Promise<void> {
  try {
    set({ jobs: sorted(await listJobs()), loaded: true, error: undefined });
  } catch (error) {
    set({ loaded: true, error: toApiError(error) });
  }
}

/** Apply one job snapshot (from an event or an action's response). */
export function upsertJob(job: Job): void {
  const previous = state.jobs.find((j) => j.id === job.id);
  const others = state.jobs.filter((j) => j.id !== job.id);
  set({ jobs: sorted([job, ...others]) });
  if (
    job.kind === "analyze" &&
    previous?.state !== job.state &&
    ["ready", "failed", "cancelled"].includes(job.state)
  )
    invalidate("sessions:");
  const finished = previous?.state !== job.state && job.state === "ready";
  if (
    finished &&
    (job.kind === "import" || job.kind === "check_sources" || job.kind === "relink")
  ) {
    invalidate("assets");
  }
  if (finished && job.kind === "proxy") {
    const assetId = (job.params as { asset_id?: string } | undefined)?.asset_id;
    invalidate(assetId ? `derived:${assetId}` : "derived:");
  }
  if (previous?.state !== job.state && job.state === "failed" && job.kind === "proxy") {
    invalidate("derived:");
  }
  if (finished && (job.kind === "group" || job.kind === "align")) {
    invalidate("sessions");
  }
  // A transcription keeps completed clips even when it fails or is cancelled.
  if (previous?.state !== job.state && job.kind === "render" && !isActive(job)) {
    const projectId = (job.params as { project_id?: string } | undefined)?.project_id;
    invalidate(projectId ? `renders:${projectId}` : "renders:");
  }
  if (previous?.state !== job.state && job.kind === "transcribe" && !isActive(job)) {
    invalidate("transcript:");
  }
  // Searchable text changes when indexing, transcription, analysis or imports finish.
  if (
    previous?.state !== job.state &&
    !isActive(job) &&
    ["index", "transcribe", "analyze", "import", "group"].includes(job.kind)
  ) {
    invalidate("search", "collection");
  }
}

/** For tests. */
export function resetJobs(): void {
  state = { jobs: [], loaded: false, error: undefined };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useJobs(): JobsState {
  return useSyncExternalStore(subscribe, () => state);
}

/** Connect the store to host events once, for the lifetime of the app. */
export function useJobFeed(workerReady: boolean): void {
  useEffect(() => {
    if (!workerReady) return;
    void reloadJobs();
    invalidate();
    let stopped = false;
    const subscriptions: Promise<UnlistenFn>[] = [
      listen<{ job?: Job }>(JOB_EVENT, (event) => {
        if (!stopped && event.payload.job) upsertJob(event.payload.job);
      }),
      listen(RESYNC_EVENT, () => {
        if (stopped) return;
        void reloadJobs();
        invalidate();
      }),
    ];
    return () => {
      stopped = true;
      for (const subscription of subscriptions) void subscription.then((stop) => stop());
    };
  }, [workerReady]);
}

/** Percent complete, or null when the job reports no measurable progress. */
export function percent(job: Job): number | null {
  const progress = job.progress;
  if (!progress || progress.total < 1) return null;
  return Math.round((100 * progress.done) / progress.total);
}
