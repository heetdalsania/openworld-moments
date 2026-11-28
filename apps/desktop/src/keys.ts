// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * M38: platform words for keys and the file manager. macOS shows ⌘ and Finder; Windows
 * keeps Ctrl and File Explorer, exactly as before.
 *
 * Detected from the webview's user agent so labels are right on the first render. The
 * macOS WebKit user agent always contains "Macintosh".
 */
export function isMac(userAgent: string = globalThis.navigator?.userAgent ?? ""): boolean {
  return /Macintosh|Mac OS X/.test(userAgent);
}

/** The primary shortcut modifier: "⌘" on macOS, "Ctrl" elsewhere. */
export function modKey(mac: boolean = isMac()): string {
  return mac ? "⌘" : "Ctrl";
}

/**
 * A shortcut in the platform's notation, modifiers in each platform's usual order:
 * `shortcut(["Mod", "Shift", "Z"])` is "⇧⌘Z" on macOS (⌃⌥⇧⌘) and "Ctrl+Shift+Z" on
 * Windows (Ctrl, Alt, Shift).
 */
export function shortcut(keys: string[], mac: boolean = isMac()): string {
  const MAC: Record<string, string> = { Mod: "⌘", Shift: "⇧", Alt: "⌥", Ctrl: "⌃" };
  const OTHER: Record<string, string> = { Mod: "Ctrl", Alt: "Alt", Shift: "Shift", Ctrl: "Ctrl" };
  const order = mac ? ["Ctrl", "Alt", "Shift", "Mod"] : ["Mod", "Ctrl", "Alt", "Shift"];
  const rank = (k: string) => {
    const i = order.indexOf(k);
    return i < 0 ? order.length : i;
  };
  const sorted = [...keys].sort((a, b) => rank(a) - rank(b));
  return mac ? sorted.map((k) => MAC[k] ?? k).join("") : sorted.map((k) => OTHER[k] ?? k).join("+");
}

/** `aria-keyshortcuts` notation (Meta on macOS, Control elsewhere). */
export function ariaShortcut(keys: string[], mac: boolean = isMac()): string {
  return keys
    .map((k) => (k === "Mod" ? (mac ? "Meta" : "Control") : k === "Ctrl" ? "Control" : k))
    .join("+");
}

/** "Finder" or "File Explorer". */
export function fileManagerName(mac: boolean = isMac()): string {
  return mac ? "Finder" : "File Explorer";
}

/** "Show in Finder" on macOS; the Windows label is unchanged ("Show in folder"). */
export function revealLabel(mac: boolean = isMac()): string {
  return mac ? "Show in Finder" : "Show in folder";
}
