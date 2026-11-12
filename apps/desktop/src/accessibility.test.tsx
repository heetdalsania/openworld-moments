// SPDX-License-Identifier: AGPL-3.0-or-later
/// <reference types="node" />
// M31 automated accessibility checks: axe-core over the primary screens, and WCAG
// contrast for every theme's color tokens (jsdom cannot compute rendered contrast, so
// the tokens are checked directly from the stylesheet).
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resetJobs } from "./jobs";
import { resetQueries } from "./query";
import { asset, createHost, type FakeHost, install } from "./testing/fakeHost";
import { setPreferencesForTest } from "./testing/setup";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({ onDragDropEvent: () => Promise.resolve(() => undefined) }),
}));

let host: FakeHost;

async function violations(): Promise<string[]> {
  const result = await axe.run(document.body, {
    // Rendered contrast needs a layout engine; tokens are checked below instead.
    rules: { "color-contrast": { enabled: false } },
  });
  return result.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`,
  );
}

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/assets?order=newest&limit=60", [asset()]);
  host.route("GET /v1/jobs?limit=200", []);
  host.route("GET /v1/projects", []);
  host.route("GET /v1/sessions*", []);
  host.route("GET /v1/system-doctor", {
    schema_version: "1.23",
    ready: true,
    packaged: true,
    platform: "Windows",
    architecture: "AMD64",
    free_bytes: 1e10,
    checks: [{ id: "storage", status: "pass", message: "Enough free space" }],
    tools: [],
  });
  host.route("GET /v1/model-manager", { schema_version: "1.23", catalog_version: 1, models: [] });
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.fontSize = "";
});

describe("axe-core finds no violations", () => {
  it.each([
    ["library", ""],
    ["settings", "#/settings"],
    ["search", "#/search"],
    ["projects", "#/projects"],
    ["phone import", "#/phone"],
  ])("on the %s screen", async (_name, hash) => {
    window.location.hash = hash;
    render(<App />);
    await screen.findByRole("heading", { level: 1 });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(await violations()).toEqual([]);
  });

  it("on every first-run setup step, reached with the keyboard", async () => {
    setPreferencesForTest({});
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Welcome to OpenWorld Moments" }));
    const user = userEvent.setup();
    for (let step = 0; step < 6; step += 1) {
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(await violations()).toEqual([]);
      const next =
        screen.queryByRole("button", { name: "Start setup" }) ??
        screen.queryByRole("button", { name: "Continue" });
      if (!next) break;
      next.focus();
      await user.keyboard("{Enter}");
    }
    expect(screen.getByRole("heading", { level: 1, name: "You're ready" })).toBeTruthy();
  });

  it("on the phone screen before transfer is allowed", async () => {
    setPreferencesForTest({ onboarding: "completed" });
    window.location.hash = "#/phone";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Phone transfer is off" })).toBeTruthy();
    expect(await violations()).toEqual([]);
  });
});

// -- WCAG 2.2 contrast of the theme tokens ---------------------------------------------

// Vitest serves CSS imports empty, so read the stylesheet from disk.
const stylesheet = ["src/styles.css", "apps/desktop/src/styles.css"]
  .map((p) => resolve(process.cwd(), p))
  .find((p) => existsSync(p));
const css = stylesheet ? readFileSync(stylesheet, "utf8") : "";

function block(selector: string, nth = 0): Record<string, string> {
  let from = 0;
  let index = -1;
  for (let i = 0; i <= nth; i += 1) {
    index = css.indexOf(selector, from);
    if (index < 0) throw new Error(`missing ${selector}`);
    from = index + selector.length;
  }
  const body = css.slice(css.indexOf("{", index) + 1, css.indexOf("}", index));
  return Object.fromEntries(
    [...body.matchAll(/--([a-z-]+):\s*(#[0-9a-f]{6})\s*;/gi)].map((m) => [m[1], m[2]]),
  );
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const ROOT = "\n:root {";
const DARK = "@media (prefers-color-scheme: dark) {\n  :root {";
const THEMES: Record<string, Record<string, string>> = {
  "system light": { ...block(ROOT), ...block(ROOT, 1) },
  "system dark": {
    ...block(ROOT),
    ...block(ROOT, 1),
    ...block(DARK),
    ...block(DARK, 1),
  },
  light: block(':root[data-theme="light"]'),
  dark: block(':root[data-theme="dark"]'),
  "high contrast": block(':root[data-theme="high-contrast"]'),
};

describe("theme colors meet WCAG AA (AAA for high contrast)", () => {
  it.each(Object.entries(THEMES))("%s", (name, t) => {
    const text = name === "high contrast" ? 7 : 4.5;
    const need = (fg: string, bg: string) => {
      const value = t[fg] && t[bg] ? contrast(t[fg], t[bg]) : 0;
      return `${fg} on ${bg}: ${value.toFixed(2)}`;
    };
    const pairs: [string, string, number][] = [
      ["fg", "bg", text],
      ["muted", "bg", name === "high contrast" ? 7 : 4.5],
      ["accent", "bg", text], // links
      ["accent-fg", "accent", text], // primary buttons
      ["warn", "bg", 4.5],
      ["focus", "bg", 3], // non-text: focus indicator
    ];
    for (const [fg, bg, min] of pairs) {
      expect(t[fg], `${name} defines --${fg}`).toBeTruthy();
      expect(contrast(t[fg] ?? "#000000", t[bg] ?? "#000000"), need(fg, bg)).toBeGreaterThanOrEqual(
        min,
      );
    }
  });

  it("measures known pairs correctly", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });
});
