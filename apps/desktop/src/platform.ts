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

/**
 * M38: which macOS download suits this Mac. An Intel build under Rosetta means the Mac
 * has Apple Silicon. `null` off macOS, or when an Intel build can't tell whether it is
 * translated.
 */
export function recommendedDownload(
  info: PlatformCapabilities,
): { arch: "arm64" | "x86_64"; label: string } | null {
  if (info.os.family !== "macos") return null;
  if (info.architecture.binary === "aarch64" || info.architecture.translated === true)
    return { arch: "arm64", label: "Apple Silicon (arm64)" };
  if (info.architecture.translated === false) return { arch: "x86_64", label: "Intel (x86_64)" };
  return null;
}

/** The release DMG name for an architecture (ADR-0008 naming). */
export function dmgName(version: string, arch: "arm64" | "x86_64"): string {
  return `OpenWorld-Moments_${version}_macOS_${arch}.dmg`;
}

const SIGNING = {
  "not-applicable": null,
  unknown: "Signature could not be checked",
  unsigned: "Not signed",
  adhoc: "Signed ad hoc for testing; not notarized by Apple",
  "developer-id": "Signed with a Developer ID; not notarized by Apple",
  notarized: "Signed with a Developer ID and notarized by Apple",
  other: "Signed with a development certificate; not notarized by Apple",
} as const;

/**
 * M38: how this copy is signed, in words. Only "notarized" claims notarization, and only
 * the host can report it (after Gatekeeper accepted the bundle as notarized).
 */
export function signingName(info: PlatformCapabilities): string | null {
  return info.signing ? SIGNING[info.signing.state] : null;
}
