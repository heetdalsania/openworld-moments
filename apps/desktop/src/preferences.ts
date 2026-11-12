// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * M31 per-user preferences: setup progress, privacy choices and appearance.
 *
 * Stored in the webview's local storage under one versioned key. Missing, unreadable or
 * malformed data falls back to the defaults below, and the privacy defaults are the safe
 * ones: phone transfer over the local network and optional model downloads stay off until
 * the user turns them on with an explanation in front of them.
 */
import { useSyncExternalStore } from "react";

export const PREFERENCES_KEY = "owm.preferences.v1";

export type Theme = "system" | "light" | "dark" | "high-contrast";
export type Motion = "system" | "reduce";
export const TEXT_SIZES = [100, 125, 150, 175, 200] as const;
export type TextSize = (typeof TEXT_SIZES)[number];

export interface Preferences {
  /** "pending" until the user finishes or skips first-run setup. */
  onboarding: "pending" | "completed" | "skipped";
  privacy: {
    /** Phone transfer over the local network (spec 14: off by default). */
    phoneLan: boolean;
    /** Optional speech-model downloads from the signed catalog. */
    modelDownloads: boolean;
  };
  appearance: { theme: Theme; textSize: TextSize; motion: Motion };
}

export const DEFAULTS: Preferences = {
  onboarding: "pending",
  privacy: { phoneLan: false, modelDownloads: false },
  appearance: { theme: "system", textSize: 100, motion: "system" },
};

const THEMES: readonly Theme[] = ["system", "light", "dark", "high-contrast"];
const MOTIONS: readonly Motion[] = ["system", "reduce"];
const ONBOARDING: readonly Preferences["onboarding"][] = ["pending", "completed", "skipped"];

function pick<T>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** Parse stored JSON into preferences, keeping only known values. */
export function parsePreferences(raw: string | null): Preferences {
  let data: Record<string, unknown> = {};
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
      data = parsed as Record<string, unknown>;
  } catch {
    // Corrupt storage behaves like a fresh profile.
  }
  const privacy = (data.privacy ?? {}) as Record<string, unknown>;
  const appearance = (data.appearance ?? {}) as Record<string, unknown>;
  return {
    onboarding: pick(data.onboarding, ONBOARDING, DEFAULTS.onboarding),
    privacy: {
      phoneLan: privacy.phoneLan === true,
      modelDownloads: privacy.modelDownloads === true,
    },
    appearance: {
      theme: pick(appearance.theme, THEMES, DEFAULTS.appearance.theme),
      textSize: pick(appearance.textSize, TEXT_SIZES, DEFAULTS.appearance.textSize),
      motion: pick(appearance.motion, MOTIONS, DEFAULTS.appearance.motion),
    },
  };
}

let current: Preferences | null = null;
const listeners = new Set<() => void>();

function read(): Preferences {
  try {
    return parsePreferences(window.localStorage.getItem(PREFERENCES_KEY));
  } catch {
    return DEFAULTS;
  }
}

export function getPreferences(): Preferences {
  current ??= read();
  return current;
}

export function updatePreferences(change: (prefs: Preferences) => Preferences): Preferences {
  const next = parsePreferences(JSON.stringify(change(getPreferences())));
  current = next;
  try {
    window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(next));
  } catch {
    // Storage can be unavailable; the choice still applies until the app closes.
  }
  applyAppearance(next.appearance);
  for (const listener of listeners) listener();
  return next;
}

export function setPrivacy(key: keyof Preferences["privacy"], value: boolean): void {
  updatePreferences((p) => ({ ...p, privacy: { ...p.privacy, [key]: value } }));
}

export function setAppearance(change: Partial<Preferences["appearance"]>): void {
  updatePreferences((p) => ({ ...p, appearance: { ...p.appearance, ...change } }));
}

export function setOnboarding(state: Preferences["onboarding"]): void {
  updatePreferences((p) => ({ ...p, onboarding: state }));
}

/** Forget the cached copy (tests, or after storage was changed elsewhere). */
export function reloadPreferences(): void {
  current = null;
  applyAppearance(getPreferences().appearance);
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePreferences(): Preferences {
  return useSyncExternalStore(subscribe, getPreferences, getPreferences);
}

/**
 * Reflect appearance on the root element: `data-theme`, `data-motion` and the root font
 * size (the stylesheet sizes text and spacing in rem, so everything scales together).
 */
export function applyAppearance(appearance: Preferences["appearance"]): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (appearance.theme === "system") delete root.dataset.theme;
  else root.dataset.theme = appearance.theme;
  if (appearance.motion === "system") delete root.dataset.motion;
  else root.dataset.motion = appearance.motion;
  root.style.fontSize = appearance.textSize === 100 ? "" : `${appearance.textSize}%`;
}

/** Thrown by feature entry points when the user has not opted in. */
export class ConsentRequired extends Error {
  readonly code = "consent.required";
  readonly retryable = false;
  constructor(readonly feature: keyof Preferences["privacy"]) {
    super(
      feature === "phoneLan"
        ? "Turn on phone transfer in Settings → Privacy choices first."
        : "Allow optional model downloads in Settings → Privacy choices first.",
    );
  }
}

export function requireConsent(feature: keyof Preferences["privacy"]): void {
  if (!getPreferences().privacy[feature]) throw new ConsentRequired(feature);
}
