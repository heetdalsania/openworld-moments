// SPDX-License-Identifier: AGPL-3.0-or-later
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

/** Mirrors `WorkerStatus` in src-tauri/src/worker/supervisor.rs. */
export type WorkerStatus =
  | { status: "stopped" }
  | { status: "starting" }
  | { status: "ready"; port: number; pid: number; restarts: number }
  | { status: "restarting"; attempt: number; reason: string }
  | { status: "failed"; code: string; message: string; stderr_tail: string };

export const STATUS_EVENT = "worker://status";

export function fetchWorkerStatus(): Promise<WorkerStatus> {
  return invoke<WorkerStatus>("worker_status");
}

export function onWorkerStatus(handler: (status: WorkerStatus) => void): Promise<UnlistenFn> {
  return listen<WorkerStatus>(STATUS_EVENT, (event) => handler(event.payload));
}

export function describeWorker(status: WorkerStatus | null): string {
  if (status === null) return "Worker: checking…";
  switch (status.status) {
    case "stopped":
      return "Worker: stopped";
    case "starting":
      return "Worker: starting…";
    case "ready":
      return status.restarts > 0
        ? `Worker: ready (restarted ${status.restarts}×)`
        : "Worker: ready";
    case "restarting":
      return `Worker: restarting (attempt ${status.attempt})`;
    case "failed":
      return `Worker unavailable: ${status.message}`;
  }
}
