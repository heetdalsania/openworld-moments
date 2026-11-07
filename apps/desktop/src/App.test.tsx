// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resetJobs } from "./jobs";
import { resetQueries } from "./query";
import { ASSET_ID, asset, createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
const drop = vi.hoisted(() => ({ handler: undefined as undefined | ((e: unknown) => void) }));
const open = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: (handler: (e: unknown) => void) => {
      drop.handler = handler;
      return Promise.resolve(() => undefined);
    },
  }),
}));

let host: FakeHost;

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/assets?order=newest&limit=60", [asset()]);
  host.route("GET /v1/jobs?limit=200", []);
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
  drop.handler = undefined;
});

describe("app shell", () => {
  it("shows navigation, global controls, and the library", async () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Library" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("button", { name: "Import" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Background jobs" })).toBeTruthy();
    expect(await screen.findByText("Heist finale.mp4")).toBeTruthy();
    expect(await screen.findByText("Version 0.0.0 (planning)")).toBeTruthy();
  });

  it("waits for the worker and explains restarts", async () => {
    host.worker = { status: "starting" };
    render(<App />);
    expect(await screen.findByText("Worker: starting…")).toBeTruthy();
    expect(screen.getByText(/library opens once the media worker is running/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Import" }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    act(() => host.emit("worker://status", { status: "ready", port: 1, pid: 2, restarts: 0 }));
    expect(await screen.findByText("Heist finale.mp4")).toBeTruthy();

    // A worker restart while the UI is open: a banner, then a fresh durable job list.
    act(() => host.emit("worker://status", { status: "restarting", attempt: 1, reason: "exited" }));
    expect(await screen.findByText(/jobs are kept and continue/)).toBeTruthy();
    host.route("GET /v1/jobs?limit=200", [job({ kind: "import", state: "probing" })]);
    act(() => host.emit("worker://status", { status: "ready", port: 1, pid: 3, restarts: 1 }));
    expect(await screen.findByRole("button", { name: "Background jobs (1 running)" })).toBeTruthy();
  });

  it("restores the asset screen after a reload", async () => {
    host.route(`GET /v1/assets/${ASSET_ID}`, asset());
    host.route(`GET /v1/assets/${ASSET_ID}/derived`, {
      schema_version: "1.6",
      asset_id: ASSET_ID,
      proxy_decision: { needed: false, policy: "auto", policy_version: 1, reasons: [] },
      artifacts: [
        { kind: "proxy", status: "not_needed" },
        {
          kind: "filmstrip",
          status: "failed",
          last_error: { code: "x.y", message: "m", retryable: false },
        },
        {
          kind: "waveform",
          status: "failed",
          last_error: { code: "x.y", message: "m", retryable: false },
        },
      ],
    });
    window.location.hash = `#/asset/${ASSET_ID}`;
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Heist finale.mp4", level: 1 })).toBeTruthy();
  });

  it("opens the import dialog with dropped files", async () => {
    render(<App />);
    await screen.findByText("Heist finale.mp4");
    act(() => drop.handler?.({ payload: { type: "over", position: { x: 1, y: 1 } } }));
    expect(screen.getByText("Drop videos or folders to import")).toBeTruthy();
    act(() =>
      drop.handler?.({
        payload: { type: "drop", paths: ["/captures/a.mp4", "/captures/b.mkv"], position: {} },
      }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Import media" });
    expect(within(dialog).getByText("a.mp4")).toBeTruthy();
    expect(within(dialog).getByText("b.mkv")).toBeTruthy();
  });

  it("keeps running jobs visible across navigation", async () => {
    host.route("GET /v1/jobs?limit=200", [
      job({ kind: "proxy", state: "proxying", progress: { done: 400, total: 1000 } }),
    ]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Background jobs (1 running)" }));
    expect(await screen.findByLabelText("Prepare playback progress")).toBeTruthy();
    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(screen.getByRole("heading", { name: "Settings" })).toBeTruthy();
    expect(screen.getByLabelText("Prepare playback progress")).toBeTruthy();
  });
});

describe("keyboard-only walkthrough", () => {
  it("reaches every primary control and imports without a mouse", async () => {
    open.mockResolvedValue(["/captures/clip.mp4"]);
    host.route("POST /v1/imports", job({ kind: "import", state: "queued" }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Heist finale.mp4");

    await user.tab();
    expect(document.activeElement?.textContent).toBe("Skip to content");
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Library");
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Settings");
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Import");
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Import from phone");
    await user.tab();
    expect(document.activeElement?.textContent).toMatch(/^Background jobs/);
    await user.tab();
    expect(document.activeElement?.textContent).toBe("Refresh");
    await user.tab();
    expect(document.activeElement?.textContent).toContain("Heist finale.mp4"); // the clip card

    // Open Import from the keyboard; focus moves into the dialog.
    await user.tab({ shift: true });
    await user.tab({ shift: true });
    await user.tab({ shift: true });
    await user.tab({ shift: true });
    expect(document.activeElement?.textContent).toBe("Import");
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog", { name: "Import media" });
    expect(document.activeElement?.textContent).toBe("Choose files…");
    await user.keyboard("{Enter}");
    expect(await within(dialog).findByText("clip.mp4")).toBeTruthy();
    const start = within(dialog).getByRole("button", { name: "Import 1" });
    start.focus();
    await user.keyboard("{Enter}");
    expect(host.posts("/v1/imports")).toEqual([
      { paths: ["/captures/clip.mp4"], mode: "reference", recursive: true },
    ]);
    // Starting an import opens the job center.
    expect(await screen.findByRole("heading", { name: "Background jobs" })).toBeTruthy();
  });

  it("closes the import dialog with Escape", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Heist finale.mp4");
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
