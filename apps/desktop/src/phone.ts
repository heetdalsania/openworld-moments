// SPDX-License-Identifier: AGPL-3.0-or-later
// "Import from phone" (M10): host commands and events for the temporary LAN gateway.
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { toApiError } from "./api";
import { requireConsent } from "./preferences";

export const PHONE_EVENT = "phone://status";

export interface NetInterface {
  name: string;
  address: string;
}

/** Mirrors `PhoneUpload` in src-tauri/src/phone.rs. */
export interface PhoneUpload {
  seq: number;
  name: string;
  size: number;
  received: number;
  status:
    | "receiving"
    | "importing"
    | "imported"
    | "duplicate"
    | "import_failed"
    | "rejected"
    | "interrupted";
  reason?: string;
  asset_id?: string;
}

/** Mirrors `PhoneStatus` in src-tauri/src/phone.rs. */
export interface PhoneStatus {
  state: "idle" | "starting" | "active" | "ended";
  address?: string;
  port?: number;
  url?: string;
  qr_svg?: string;
  expires_in_s?: number;
  uploads: PhoneUpload[];
  ended_reason?: string;
  error?: { code: string; message: string };
}

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(command, args);
  } catch (error) {
    throw toApiError(error);
  }
}

export function phoneInterfaces(): Promise<NetInterface[]> {
  return call("phone_interfaces");
}

export function phoneStatus(): Promise<PhoneStatus> {
  return call("phone_status");
}

export async function startPhone(address: string, port?: number): Promise<PhoneStatus> {
  // M31: the LAN page needs an explicit opt-in, checked here as well as in the screen.
  requireConsent("phoneLan");
  return call("phone_start", { address, port: port ?? null });
}

export function stopPhone(): Promise<PhoneStatus> {
  return call("phone_stop");
}

export function onPhoneStatus(handler: (status: PhoneStatus) => void): Promise<UnlistenFn> {
  return listen<PhoneStatus>(PHONE_EVENT, (event) => handler(event.payload));
}

const REASONS: Record<string, string> = {
  unsupported_type: "Not a supported video type",
  not_video: "Not a video file",
  too_large: "Too large",
  session_full: "Session size limit reached",
  too_many_files: "File limit reached",
  disk_full: "Not enough free space",
  size_mismatch: "Sent more data than announced",
  expired: "Session expired",
  interrupted: "Connection lost",
  busy: "Busy",
  "media.damaged": "Damaged or incomplete video",
  "media.unsupported_format": "Not a playable video",
  "media.no_video_stream": "No video in this file",
};

export function describeUpload(upload: PhoneUpload): string {
  switch (upload.status) {
    case "receiving":
      return upload.size > 0
        ? `Receiving ${Math.round((100 * upload.received) / upload.size)}%`
        : "Receiving";
    case "importing":
      return "Received, adding to the library…";
    case "imported":
      return "Added to the library";
    case "duplicate":
      return "Already in the library";
    case "import_failed":
      return `Not added: ${REASONS[upload.reason ?? ""] ?? upload.reason ?? "import failed"}`;
    case "rejected":
      return `Refused: ${REASONS[upload.reason ?? ""] ?? upload.reason ?? "not accepted"}`;
    case "interrupted":
      return "Interrupted, nothing was kept";
  }
}

const ENDED: Record<string, string> = {
  expired: "The upload link expired after 10 minutes.",
  finished_on_phone: "The phone finished the session.",
  closed_by_desktop: "You closed the upload link.",
  stopped: "The upload link was closed.",
  ended: "The upload link was closed.",
};

export function describeEnd(reason: string | undefined): string {
  return ENDED[reason ?? "ended"] ?? "The upload link was closed.";
}
