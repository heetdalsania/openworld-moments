// SPDX-License-Identifier: AGPL-3.0-or-later
/// <reference types="node" />
// M38: native macOS menus and shortcuts, Open Recent, the Quit check, architecture and
// signing words, macOS setup and permission guidance, and that Windows is unchanged.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PlatformCapabilities } from "@openworld-moments/contracts";
import { App } from "./App";
import { resetJobs } from "./jobs";
import { ariaShortcut, isMac, modKey, revealLabel, shortcut } from "./keys";
import { MacPermissions } from "./MacPermissions";
import {
  clearRecentProjects,
  MENU_EVENT,
  type MenuHandlers,
  RECENT_KEY,
  RECENT_LIMIT,
  recentProjects,
  rememberProject,
  runMenuAction,
} from "./menu";
import { Onboarding, setupSteps } from "./Onboarding";
import { dmgName, recommendedDownload, signingName } from "./platform";
import { getPreferences, setAppearance } from "./preferences";
import { resetQueries } from "./query";
import { shortcutGroups, ShortcutsDialog } from "./ShortcutsDialog";
import { SystemPanel } from "./SystemPanel";
import { asset, createHost, type FakeHost, install, windowsPlatform } from "./testing/fakeHost";
import { setPreferencesForTest } from "./testing/setup";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({ onDragDropEvent: () => Promise.resolve(() => undefined) }),
}));

const MAC_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)";
const WINDOWS_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/131.0";
const P1 = "prj_01JCBQ00000000000000000001";
const P2 = "prj_01JCBQ00000000000000000002";

let host: FakeHost;

function asMac(): void {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(MAC_UA);
}

function macPlatform(overrides: Partial<PlatformCapabilities> = {}): PlatformCapabilities {
  return {
    schema_version: "1.28",
    host_version: "0.1.0-alpha.37",
    os: { family: "macos", version: "26.1", minimum: "14.0" },
    architecture: { binary: "aarch64", translated: false },
    build: { target: "aarch64-apple-darwin", profile: "release", bundled_worker: true },
    support: { level: "development", reasons: ["macos-preview"] },
    directories: { convention: "macos-standard" },
    integrations: { file_manager: "finder", secret_store: "none", menus: "native" },
    signing: { state: "adhoc", hardened_runtime: true, gatekeeper: "rejected" },
    ...overrides,
  };
}

function handlers(overrides: Partial<MenuHandlers> = {}): MenuHandlers {
  return {
    ready: true,
    openImport: vi.fn(),
    openJobs: vi.fn(),
    openShortcuts: vi.fn(),
    report: vi.fn(),
    ...overrides,
  };
}

function invoked(command: string): unknown[] {
  return host.calls.filter((c) => c.path === command).map((c) => c.body);
}

beforeEach(() => {
  localStorage.removeItem(RECENT_KEY);
  host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/assets?order=newest&limit=60", [asset()]);
  host.route("GET /v1/jobs?limit=200", []);
  host.route("GET /v1/projects", []);
  host.route("GET /v1/sessions*", []);
  host.route("GET /v1/model-manager", { schema_version: "1.23", catalog_version: 1, models: [] });
  host.route("GET /v1/system-doctor", {
    schema_version: "1.26",
    ready: true,
    packaged: true,
    platform: "Darwin",
    architecture: "arm64",
    free_bytes: 1e10,
    checks: [{ id: "storage", status: "pass", message: "Enough free space" }],
    tools: [],
  });
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
  localStorage.removeItem(RECENT_KEY);
  setAppearance({ textSize: 100 });
});

describe("platform words", () => {
  it("uses ⌘ and Finder on macOS and keeps Ctrl and the Windows labels elsewhere", () => {
    expect(isMac(MAC_UA)).toBe(true);
    expect(isMac(WINDOWS_UA)).toBe(false);
    expect(isMac("")).toBe(false);
    expect(modKey(true)).toBe("⌘");
    expect(modKey(false)).toBe("Ctrl");
    expect(shortcut(["Shift", "Mod", "Z"], true)).toBe("⇧⌘Z");
    expect(shortcut(["Ctrl", "Mod", "F"], true)).toBe("⌃⌘F");
    expect(shortcut(["Mod", "Shift", "Z"], false)).toBe("Ctrl+Shift+Z");
    expect(shortcut(["Shift", "Mod", "Z"], false)).toBe("Ctrl+Shift+Z");
    expect(shortcut(["Mod", "Shift", "Z"], true)).toBe("⇧⌘Z");
    expect(ariaShortcut(["Mod", "K"], true)).toBe("Meta+K");
    expect(ariaShortcut(["Mod", "K"], false)).toBe("Control+K");
    expect(revealLabel(true)).toBe("Show in Finder");
    expect(revealLabel(false)).toBe("Show in folder");
  });
});

describe("menu actions", () => {
  it("navigates to each screen", () => {
    const cases: [string, string][] = [
      ["app.settings", "#/settings"],
      ["view.library", "#/library"],
      ["view.sessions", "#/sessions"],
      ["view.projects", "#/projects"],
      ["view.search", "#/search"],
      ["edit.find", "#/search"],
      ["file.phone", "#/phone"],
      ["file.new_project", "#/sessions"],
      ["help.diagnostics", "#/settings"],
      [`recent:${P1}`, `#/project/${P1}`],
    ];
    for (const [id, hash] of cases) {
      window.location.hash = "";
      expect(runMenuAction(id, handlers())).toBe(true);
      expect(window.location.hash).toBe(hash);
    }
  });

  it("opens Import, jobs and shortcuts, and explains Import while the worker starts", () => {
    const h = handlers();
    runMenuAction("file.import", h);
    runMenuAction("view.jobs", h);
    runMenuAction("help.shortcuts", h);
    expect(h.openImport).toHaveBeenCalledOnce();
    expect(h.openJobs).toHaveBeenCalledOnce();
    expect(h.openShortcuts).toHaveBeenCalledOnce();
    const waiting = handlers({ ready: false });
    runMenuAction("file.import", waiting);
    expect(waiting.openImport).not.toHaveBeenCalled();
    expect(waiting.report).toHaveBeenCalledWith(expect.stringMatching(/media worker/));
  });

  it("steps text size within 100–200% and resets it", () => {
    runMenuAction("view.text_bigger", handlers());
    expect(getPreferences().appearance.textSize).toBe(125);
    for (let i = 0; i < 10; i++) runMenuAction("view.text_bigger", handlers());
    expect(getPreferences().appearance.textSize).toBe(200);
    runMenuAction("view.text_smaller", handlers());
    expect(getPreferences().appearance.textSize).toBe(175);
    runMenuAction("view.text_actual", handlers());
    expect(getPreferences().appearance.textSize).toBe(100);
    runMenuAction("view.text_smaller", handlers());
    expect(getPreferences().appearance.textSize).toBe(100);
  });

  it("reruns setup and shows the library in Finder", async () => {
    runMenuAction("help.setup", handlers());
    expect(getPreferences().onboarding).toBe("pending");
    invoke.mockImplementationOnce(() => Promise.reject({ code: "x", message: "No library" }));
    const h = handlers();
    runMenuAction("file.reveal_library", h);
    await vi.waitFor(() => expect(h.report).toHaveBeenCalledWith("No library"));
  });

  it("ignores unknown or malformed IDs", () => {
    window.location.hash = "#/library";
    for (const id of [
      "",
      "app.quit.extra",
      "recent:../../x",
      "recent:ast_01JCBQ00000000000000000001",
      "view.nope",
    ]) {
      expect(runMenuAction(id, handlers())).toBe(false);
    }
    expect(window.location.hash).toBe("#/library");
  });

  it("handles every app action the native menu sends", () => {
    // The host owns Quit and the two Help links; everything else comes here.
    const rust = readFileSync(resolve(process.cwd(), "src-tauri/src/menu.rs"), "utf8");
    const layout = rust.slice(
      rust.indexOf("pub fn macos_layout"),
      rust.indexOf("pub fn action_ids"),
    );
    const ids = [...layout.matchAll(/action\(\s*"([a-z_.]+)"/g)].map((m) => m[1] ?? "");
    expect(ids.length).toBeGreaterThan(15);
    for (const id of ids) {
      if (id === "help.guides" || id === "help.mac_guide") continue;
      window.location.hash = "";
      expect(runMenuAction(id, handlers()), id).toBe(true);
    }
  });

  it("listens to the host's menu event", async () => {
    asMac();
    render(<App />);
    await screen.findByRole("heading", { name: "Library" });
    act(() => host.emit(MENU_EVENT, "app.settings"));
    expect(window.location.hash).toBe("#/settings");
    act(() => host.emit(MENU_EVENT, "help.shortcuts"));
    const dialog = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(dialog).getAllByText(/⌘/).length).toBeGreaterThan(5);
  });
});

describe("Open Recent", () => {
  it("keeps the newest ten projects and tells the native menu", () => {
    rememberProject(P1, "First");
    rememberProject(P2, "Second");
    rememberProject(P1, "First renamed");
    expect(recentProjects()).toEqual([
      { id: P1, title: "First renamed" },
      { id: P2, title: "Second" },
    ]);
    for (let i = 10; i < 30; i++) rememberProject(`prj_01JCBQ000000000000000000${i}`, `P${i}`);
    expect(recentProjects()).toHaveLength(RECENT_LIMIT);
    expect(recentProjects()[0]?.title).toBe("P29");
    const sent = invoked("menu_recent_set").at(-1) as { projects: unknown[] };
    expect(sent.projects).toHaveLength(RECENT_LIMIT);
    clearRecentProjects();
    expect(recentProjects()).toEqual([]);
    expect(invoked("menu_recent_set").at(-1)).toEqual({ projects: [] });
  });

  it("treats damaged storage as empty and drops invalid entries", () => {
    localStorage.setItem(RECENT_KEY, "{not json");
    expect(recentProjects()).toEqual([]);
    localStorage.setItem(
      RECENT_KEY,
      JSON.stringify([
        { id: "../etc", title: "x" },
        { id: P1, title: 3 },
        { id: P2, title: "ok" },
        7,
      ]),
    );
    expect(recentProjects()).toEqual([{ id: P2, title: "ok" }]);
    localStorage.setItem(RECENT_KEY, JSON.stringify({ id: P1 }));
    expect(recentProjects()).toEqual([]);
    runMenuAction("file.recent_clear", handlers());
    expect(localStorage.getItem(RECENT_KEY)).toBe("[]");
  });

  it("is sent to the menu at start-up, and Quit learns about unsaved edits", async () => {
    rememberProject(P1, "Heist");
    host.calls.length = 0;
    render(<App />);
    await screen.findByRole("heading", { name: "Library" });
    expect(invoked("menu_recent_set")).toContainEqual({ projects: [{ id: P1, title: "Heist" }] });
    expect(invoked("quit_guard_set")).toEqual([{ unsaved: false }]);
  });
});

describe("keyboard shortcuts list", () => {
  it("lists every native menu shortcut on macOS", () => {
    const rust = readFileSync(resolve(process.cwd(), "src-tauri/src/menu.rs"), "utf8");
    const layout = rust.slice(
      rust.indexOf("pub fn macos_layout"),
      rust.indexOf("pub fn action_ids"),
    );
    const accelerators = [...layout.matchAll(/Some\("(Cmd\+[^"]+)"\)/g)].map((m) => m[1] ?? "");
    expect(accelerators.length).toBeGreaterThan(10);
    const listed = shortcutGroups(true)
      .flatMap((g) => g.rows.map((r) => r.keys))
      .join(" ");
    for (const accelerator of accelerators) {
      const keys = accelerator.split("+").map((k) => (k === "Cmd" ? "Mod" : k));
      const expected = shortcut(keys, true);
      expect(listed, accelerator).toContain(expected);
    }
  });

  it("keeps Windows on Ctrl with no macOS menu section", () => {
    const groups = shortcutGroups(false);
    const text = JSON.stringify(groups);
    expect(text).not.toMatch(/[⌘⇧⌥⌃]/);
    expect(text).toContain("Ctrl+K");
    expect(text).toContain("Ctrl+Shift+Z");
    expect(groups.map((g) => g.title)).toEqual(["Everywhere", "Session player", "Story editor"]);
  });

  it("is an accessible dialog that keeps focus and closes with Escape", async () => {
    asMac();
    const user = userEvent.setup();
    const onClose = vi.fn();
    const opener = document.createElement("button");
    opener.textContent = "Open shortcuts";
    document.body.append(opener);
    opener.focus();
    render(<ShortcutsDialog onClose={onClose} />);
    const close = screen.getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(close);
    await user.tab();
    expect(document.activeElement).toBe(close);
    expect(screen.getAllByRole("table").length).toBe(4);
    const result = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations.map((v) => v.id)).toEqual([]);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
    opener.remove();
  });
});

describe("architecture and signing", () => {
  it("recommends the native DMG for this Mac", () => {
    expect(recommendedDownload(macPlatform())?.arch).toBe("arm64");
    expect(
      recommendedDownload(macPlatform({ architecture: { binary: "x86_64", translated: true } }))
        ?.arch,
    ).toBe("arm64");
    expect(
      recommendedDownload(macPlatform({ architecture: { binary: "x86_64", translated: false } }))
        ?.arch,
    ).toBe("x86_64");
    expect(
      recommendedDownload(macPlatform({ architecture: { binary: "x86_64", translated: null } })),
    ).toBeNull();
    expect(recommendedDownload(windowsPlatform() as unknown as PlatformCapabilities)).toBeNull();
    expect(dmgName("0.2.0", "arm64")).toBe("OpenWorld-Moments_0.2.0_macOS_arm64.dmg");
    expect(dmgName("0.2.0", "x86_64")).toBe("OpenWorld-Moments_0.2.0_macOS_x86_64.dmg");
  });

  it("only says notarized when the host reported notarized", () => {
    const states = ["unknown", "unsigned", "adhoc", "developer-id", "other"] as const;
    for (const state of states) {
      const name = signingName(
        macPlatform({ signing: { state, hardened_runtime: null, gatekeeper: "rejected" } }),
      );
      expect(name, state).toBeTruthy();
      expect(name, state).not.toMatch(/and notarized/);
    }
    expect(
      signingName(
        macPlatform({
          signing: { state: "notarized", hardened_runtime: true, gatekeeper: "accepted" },
        }),
      ),
    ).toMatch(/notarized by Apple/);
    expect(signingName(windowsPlatform() as unknown as PlatformCapabilities)).toBeNull();
    // A 1.27 host has no signing block: nothing is claimed.
    const older: Partial<PlatformCapabilities> = macPlatform();
    delete older.signing;
    expect(signingName(older as PlatformCapabilities)).toBeNull();
  });

  it("shows the signature and the right download in the system check", async () => {
    host.platform = macPlatform({
      architecture: { binary: "x86_64", translated: true },
      support: { level: "unsupported", reasons: ["macos-preview", "translated"] },
    });
    render(<SystemPanel />);
    expect(
      await screen.findByText(/Signature: Signed ad hoc for testing; not notarized/),
    ).toBeTruthy();
    expect(screen.getByText(/Apple Silicon \(arm64\) DMG/)).toBeTruthy();
    expect(screen.getAllByRole("alert").some((a) => /Rosetta/.test(a.textContent ?? ""))).toBe(
      true,
    );
  });
});

describe("macOS setup and permissions", () => {
  it("adds a permissions step on macOS only", () => {
    expect(setupSteps(true)).toEqual([
      "welcome",
      "system",
      "permissions",
      "import",
      "privacy",
      "display",
      "done",
    ]);
    expect(setupSteps(false)).not.toContain("permissions");
    expect(setupSteps(false)).toHaveLength(6);
  });

  it("walks the macOS setup with the keyboard through the permissions step", async () => {
    asMac();
    setPreferencesForTest({ onboarding: "pending" });
    const user = userEvent.setup();
    render(<Onboarding workerReady={false} onImport={vi.fn()} />);
    expect(screen.getByText("Setup · step 1 of 7")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Start setup" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("heading", { level: 1, name: "What macOS may ask" })).toBe(
      document.activeElement,
    );
    expect(screen.getByText("Setup · step 3 of 7")).toBeTruthy();
    const result = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });

  it("opens the right System Settings pane and the guide, and reports failures", async () => {
    const user = userEvent.setup();
    render(<MacPermissions />);
    await user.click(screen.getByRole("button", { name: "Open Files and Folders settings" }));
    await user.click(screen.getByRole("button", { name: "Open Local Network settings" }));
    await user.click(screen.getByRole("button", { name: "Open the macOS guide" }));
    expect(invoked("system_settings_open")).toEqual([
      { pane: "files-and-folders" },
      { pane: "local-network" },
    ]);
    expect(invoked("guide_open")).toEqual([{ topic: "macos-permissions" }]);
    invoke.mockImplementationOnce(() =>
      Promise.reject({ code: "open.failed", message: "The page could not be opened." }),
    );
    await user.click(screen.getByRole("button", { name: "Open Local Network settings" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/could not be opened/);
  });

  it("never tells people to weaken a system protection", () => {
    const { container } = render(<MacPermissions />);
    const text = container.textContent ?? "";
    for (const forbidden of [
      /xattr/i,
      /quarantine/i,
      /turn off the firewall/i,
      /disable (gatekeeper|the firewall|sip)/i,
      /open anyway/i,
      /sudo/i,
      /terminal/i,
    ]) {
      expect(text).not.toMatch(forbidden);
    }
    expect(text).toMatch(/keep the firewall on/);
    expect(text).toMatch(/never needs Full Disk Access/);
  });

  it("shows the guidance in Settings on macOS but not on Windows", async () => {
    window.location.hash = "#/settings";
    const { unmount } = render(<App />);
    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.queryByRole("heading", { name: "macOS permissions" })).toBeNull();
    expect(screen.getByRole("button", { name: "Show library folder" })).toBeTruthy();
    unmount();
    asMac();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "macOS permissions" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show library in Finder" })).toBeTruthy();
  });
});
