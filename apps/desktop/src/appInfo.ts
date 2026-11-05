// SPDX-License-Identifier: AGPL-3.0-or-later
import { invoke } from "@tauri-apps/api/core";

/** Mirrors `AppInfo` returned by the Rust `app_info` command. */
export interface AppInfo {
  name: string;
  version: string;
  stage: string;
}

export function fetchAppInfo(): Promise<AppInfo> {
  return invoke<AppInfo>("app_info");
}
