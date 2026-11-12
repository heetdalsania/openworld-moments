// SPDX-License-Identifier: AGPL-3.0-or-later
// Every test starts from a finished first-run setup with both optional network features
// allowed, the state the pre-M31 suites were written for. M31 tests that cover setup or
// consent call `setPreferencesForTest` to start from a fresh profile instead.
import { beforeEach } from "vitest";
import { DEFAULTS, PREFERENCES_KEY, type Preferences, reloadPreferences } from "../preferences";

export function setPreferencesForTest(prefs: Partial<Preferences>): void {
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ ...DEFAULTS, ...prefs }));
  reloadPreferences();
}

beforeEach(() => {
  setPreferencesForTest({
    onboarding: "completed",
    privacy: { phoneLan: true, modelDownloads: true },
  });
});
