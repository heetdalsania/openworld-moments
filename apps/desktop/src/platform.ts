// SPDX-License-Identifier: AGPL-3.0-or-later
// M33: what the desktop host reports about this computer and build.
import { invoke } from "@tauri-apps/api/core";
import { load, type PlatformCapabilities } from "@openworld-moments/contracts";

/** The host's `platform-capabilities` document, checked against the contract. */
export async function platformInfo(): Promise<PlatformCapabilities> {
  return load("platform-capabilities", await invoke<unknown>("platform_info"));
}

const OS_NAME = { windows: "Windows", macos: "macOS", linux: "Linux" } as const;

/** "macOS 15.2", "Windows". */
export function osName(info: PlatformCapabilities): string {
  const name = OS_NAME[info.os.family];
  return info.os.version ? `${name} ${info.os.version}` : name;
}

/** The build's CPU architecture in the words each platform uses. */
export function architectureName(info: PlatformCapabilities): string {
  const arm = info.architecture.binary === "aarch64";
  if (info.os.family === "macos") return arm ? "Apple Silicon (arm64)" : "Intel (x86_64)";
  return arm ? "Arm64" : "x64";
}

const LEVEL = {
  alpha: "Alpha",
  development: "Development build",
  unsupported: "Not supported on this computer",
} as const;

export function supportName(info: PlatformCapabilities): string {
  return LEVEL[info.support.level];
}

/** Plain-language explanations, most important first. */
export function supportNotes(info: PlatformCapabilities): string[] {
  const notes: string[] = [];
  const reasons = new Set(info.support.reasons);
  if (reasons.has("translated"))
    notes.push(
      "This is the Intel build running through Rosetta. Download the Apple Silicon (arm64) build for this Mac instead.",
    );
  if (reasons.has("os-below-minimum"))
    notes.push(`This build needs ${OS_NAME[info.os.family]} ${info.os.minimum} or newer.`);
  if (reasons.has("architecture-unsupported"))
    notes.push("This alpha is built for x64 Windows only.");
  if (reasons.has("macos-preview"))
    notes.push("macOS builds are previews. They are not a supported or signed release yet.");
  if (reasons.has("linux-development")) notes.push("Linux is used for development only.");
  return notes;
}
