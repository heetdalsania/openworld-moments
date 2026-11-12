// SPDX-License-Identifier: AGPL-3.0-or-later
// M31: first-run setup, informed opt-in, appearance, announcements, diagnostics and
// dialog focus. Everything here is driven with the keyboard.
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { Announcer, announcement } from "./Announcer";
import { installModel } from "./api";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { resetJobs, upsertJob } from "./jobs";
import { startPhone } from "./phone";
import {
  ConsentRequired,
  DEFAULTS,
  getPreferences,
  PREFERENCES_KEY,
  parsePreferences,
  setAppearance,
} from "./preferences";
import { resetQueries } from "./query";
import { asset, createHost, type FakeHost, install, job } from "./testing/fakeHost";
import { setPreferencesForTest } from "./testing/setup";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
const open = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({ onDragDropEvent: () => Promise.resolve(() => undefined) }),
}));

let host: FakeHost;
const DOCTOR = {
  schema_version: "1.23",
  ready: true,
  packaged: true,
  platform: "Windows",
  architecture: "AMD64",
  free_bytes: 1e10,
  checks: [{ id: "storage", status: "pass", message: "Enough free space" }],
  tools: [],
};

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/assets?order=newest&limit=60", [asset()]);
  host.route("GET /v1/jobs?limit=200", []);
  host.route("GET /v1/system-doctor", DOCTOR);
  host.route("GET /v1/model-manager", { schema_version: "1.23", catalog_version: 1, models: [] });
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  open.mockReset();
  resetQueries();
  resetJobs();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-motion");
  document.documentElement.style.fontSize = "";
});

const stored = () => JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? "{}");

describe("first-run setup", () => {
  beforeEach(() => setPreferencesForTest({}));

  it("explains what the app does and does not do before anything else", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome to OpenWorld Moments" }),
    ).toBeTruthy();
    const text = document.body.textContent ?? "";
    expect(text).toContain("never connects to, runs on or changes your console");
    expect(text).toContain("does not read game memory or network traffic");
    expect(text).toContain("no account to create");
    expect(screen.queryByText("Heist finale.mp4")).toBeNull(); // setup comes first
  });

  it("can be completed with the keyboard alone, saving choices as they are made", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Welcome to OpenWorld Moments" });
    screen.getByRole("button", { name: "Start setup" }).focus();
    await user.keyboard("{Enter}");
    // Focus moves to the new step's heading.
    const system = screen.getByRole("heading", { level: 1, name: "Welcome — check this computer" });
    await waitFor(() => expect(document.activeElement).toBe(system));
    expect(await screen.findByText("Core checks passed")).toBeTruthy();

    screen.getByRole("button", { name: "Continue" }).focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { level: 1, name: "How your clips get here" })).toBeTruthy();
    const managed = screen.getByRole("radio", { name: /Copy into the library \(managed\)/ });
    managed.focus();
    await user.keyboard(" ");
    expect(localStorage.getItem("owm.import.mode")).toBe("managed");

    screen.getByRole("button", { name: "Continue" }).focus();
    await user.keyboard("{Enter}");
    const phone = screen.getByRole("checkbox", { name: "Allow phone transfer on my home network" });
    const models = screen.getByRole("checkbox", { name: "Allow optional speech-model downloads" });
    expect((phone as HTMLInputElement).checked).toBe(false); // off by default
    expect((models as HTMLInputElement).checked).toBe(false);
    expect(phone.getAttribute("aria-describedby")).toBeTruthy(); // explained before opting in
    phone.focus();
    await user.keyboard(" ");
    expect(stored().privacy).toEqual({ phoneLan: true, modelDownloads: false });

    screen.getByRole("button", { name: "Continue" }).focus();
    await user.keyboard("{Enter}");
    const theme = screen.getByRole("combobox", { name: "Theme" });
    await user.selectOptions(theme, "high-contrast");
    expect(document.documentElement.dataset.theme).toBe("high-contrast");

    screen.getByRole("button", { name: "Continue" }).focus();
    await user.keyboard("{Enter}");
    screen.getByRole("button", { name: "Go to the library" }).focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Heist finale.mp4")).toBeTruthy();
    expect(stored().onboarding).toBe("completed");
  });

  it("can be skipped from any step, and run again from Settings", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Skip setup" }));
    expect(await screen.findByText("Heist finale.mp4")).toBeTruthy();
    expect(stored()).toMatchObject({
      onboarding: "skipped",
      privacy: { phoneLan: false, modelDownloads: false },
    });

    window.location.hash = "#/settings";
    await user.click(await screen.findByRole("button", { name: "Run setup again" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome to OpenWorld Moments" }),
    ).toBeTruthy();
  });

  it("does not block on the system check while the worker starts", async () => {
    host.worker = { status: "starting" };
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Start setup" }));
    expect(screen.getByText(/The media worker is still starting/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
  });
});

describe("informed opt-in", () => {
  it("keeps the phone page closed until transfer is allowed", async () => {
    setPreferencesForTest({ onboarding: "completed" });
    host.route("GET /v1/assets?order=newest&limit=60", []);
    const user = userEvent.setup();
    window.location.hash = "#/phone";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Phone transfer is off" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show QR code" })).toBeNull();
    await expect(startPhone("192.168.1.2")).rejects.toBeInstanceOf(ConsentRequired);
    expect(invoke.mock.calls.some(([command]) => command === "phone_start")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Allow phone transfer on this network" }));
    expect(getPreferences().privacy.phoneLan).toBe(true);
    expect(screen.queryByRole("heading", { name: "Phone transfer is off" })).toBeNull();
  });

  it("does not download a model until downloads are allowed", async () => {
    setPreferencesForTest({ onboarding: "completed" });
    host.route("GET /v1/model-manager", {
      schema_version: "1.23",
      catalog_version: 1,
      models: [
        {
          name: "tiny.en",
          revision: "abc",
          size_bytes: 77704715,
          sha256: "a".repeat(64),
          license: "MIT",
          source_url: "https://example.invalid/tiny.en",
          downloaded_bytes: 0,
          disk_required_bytes: 77704715,
          active_sha256: null,
          versions: [],
        },
      ],
    });
    const user = userEvent.setup();
    window.location.hash = "#/settings";
    render(<App />);
    const install = await screen.findByRole("button", { name: "Install tiny.en" });
    expect((install as HTMLButtonElement).disabled).toBe(true);
    await expect(installModel("tiny.en")).rejects.toBeInstanceOf(ConsentRequired);
    expect(host.posts("/v1/model-manager/download")).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Allow optional model downloads" }));
    expect((install as HTMLButtonElement).disabled).toBe(false);
    expect(host.posts("/v1/model-manager/download")).toEqual([]); // still only on Install
  });
});

describe("preferences", () => {
  it("falls back to safe defaults for missing or malformed data", () => {
    expect(parsePreferences(null)).toEqual(DEFAULTS);
    expect(parsePreferences("not json")).toEqual(DEFAULTS);
    expect(parsePreferences("[1,2]")).toEqual(DEFAULTS);
    expect(
      parsePreferences(
        JSON.stringify({
          onboarding: "done?",
          privacy: { phoneLan: "yes", modelDownloads: 1 },
          appearance: { theme: "neon", textSize: 300, motion: "fast" },
        }),
      ),
    ).toEqual(DEFAULTS);
  });

  it("applies theme, text size and motion to the whole app", () => {
    setAppearance({ theme: "dark", textSize: 200, motion: "reduce" });
    const root = document.documentElement;
    expect(root.dataset.theme).toBe("dark");
    expect(root.dataset.motion).toBe("reduce");
    expect(root.style.fontSize).toBe("200%");
    setAppearance({ theme: "system", textSize: 100, motion: "system" });
    expect(root.dataset.theme).toBeUndefined();
    expect(root.dataset.motion).toBeUndefined();
    expect(root.style.fontSize).toBe("");
  });
});

describe("announcements", () => {
  it("phrases completion, cancellation and failure", () => {
    expect(announcement(job({ kind: "render", state: "ready" }))).toEqual({
      text: "Render video finished.",
      urgent: false,
    });
    expect(
      announcement(
        job({
          kind: "import",
          state: "failed",
          error: { code: "x", message: "Disk full", retryable: false },
        }),
      ),
    ).toEqual({ text: "Import failed: Disk full", urgent: true });
    expect(announcement(job({ kind: "diagnostic", state: "ready" }))).toBeNull();
    expect(announcement(job({ kind: "render", state: "rendering" }))).toBeNull();
  });

  it("announces jobs that end while the app is open, not old history", async () => {
    upsertJob(job({ id: "job_01JCBQ0000000000000000OLD1", kind: "import", state: "ready" }));
    render(<Announcer />);
    const polite = screen.getByTestId("announce-polite");
    const urgent = screen.getByTestId("announce-urgent");
    act(() =>
      upsertJob(job({ id: "job_01JCBQ0000000000000000OLD1", kind: "import", state: "ready" })),
    );
    expect(polite.textContent).toBe("");

    act(() =>
      upsertJob(job({ id: "job_01JCBQ00000000000000000R01", kind: "render", state: "rendering" })),
    );
    act(() =>
      upsertJob(job({ id: "job_01JCBQ00000000000000000R01", kind: "render", state: "ready" })),
    );
    expect(polite.textContent).toBe("Render video finished.");

    act(() =>
      upsertJob(job({ id: "job_01JCBQ00000000000000000I01", kind: "import", state: "queued" })),
    );
    act(() =>
      upsertJob(
        job({
          id: "job_01JCBQ00000000000000000I01",
          kind: "import",
          state: "failed",
          error: { code: "import.unreadable", message: "Not a video", retryable: false },
        }),
      ),
    );
    expect(urgent.textContent).toBe("Import failed: Not a video");
  });
});

describe("diagnostics", () => {
  const report = {
    schema_version: "1.24",
    generated_at: "2026-11-11T12:00:00Z",
    worker: { api_version: "1", schema_version: "1.24", worker_version: "0.1.0" },
    system: { available: false },
    library: {
      clips: 3,
      sessions: 1,
      projects: 0,
      renders: 0,
      watched_folders: 0,
      collections: 0,
      event_observations: 0,
      transcript_segments: 0,
      database_schema: 19,
    },
    models: [],
    jobs: { totals: [], recent_failures: [] },
    privacy: {
      footage: "never included",
      file_names: "removed",
      paths: "removed",
      tokens: "removed",
      failure_messages: "omitted",
    },
  };

  it("previews the redacted report before saving it", async () => {
    host.route("POST /v1/diagnostics", (body: unknown) => ({
      report: {
        ...report,
        privacy: {
          ...report.privacy,
          failure_messages: (body as { include_messages: boolean }).include_messages
            ? "included, redacted"
            : "omitted",
        },
      },
      content: '{\n  "schema_version": "1.24"\n}\n',
      filename: "openworld-moments-diagnostics-20261111.json",
    }));
    const base = invoke.getMockImplementation();
    invoke.mockImplementation((command: string, args?: Record<string, unknown>) =>
      command === "diagnostics_export"
        ? Promise.resolve({ saved: true, warnings: [] })
        : base?.(command, args),
    );
    const user = userEvent.setup();
    render(<DiagnosticsPanel workerReady />);
    const save = screen.getByRole("button", { name: "Save report…" });
    expect((save as HTMLButtonElement).disabled).toBe(true); // preview first

    await user.click(screen.getByRole("checkbox", { name: /Include error messages/ }));
    await user.click(screen.getByRole("button", { name: "Preview report" }));
    const preview = await screen.findByRole("region", { name: "Report preview" });
    expect(preview.textContent).toContain('"schema_version": "1.24"');
    expect(screen.getByText(/error messages included, redacted/)).toBeTruthy();
    expect(host.posts("/v1/diagnostics")).toEqual([{ include_messages: true }]);

    await user.click(save);
    expect(await screen.findByText("Report saved.")).toBeTruthy();
    expect(invoke).toHaveBeenCalledWith("diagnostics_export", { includeMessages: true });
  });
});

describe("import dialog focus", () => {
  it("keeps Tab inside the dialog and returns focus to Import on Escape", async () => {
    const user = userEvent.setup();
    render(<App />);
    const importButton = await screen.findByRole("button", { name: "Import" });
    await waitFor(() => expect((importButton as HTMLButtonElement).disabled).toBe(false));
    importButton.focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Import media" });
    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Choose files…" }),
    );
    for (let i = 0; i < 12; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(importButton);
  });
});
