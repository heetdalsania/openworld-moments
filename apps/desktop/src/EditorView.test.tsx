// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { load, type EditorProject } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { App } from "./App";
import { EditorView } from "./EditorView";
import { CreateProject } from "./CreateProject";
import { ProjectsView } from "./ProjectsView";
import { resetJobs } from "./jobs";
import { resetQueries } from "./query";
import { openWorkspace, resetWorkspaces } from "./projectWorkspace";
import { asset, createHost, install, type FakeHost } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({ onDragDropEvent: () => Promise.resolve(() => undefined) }),
}));
let host: FakeHost, document: EditorProject, revision: number, failSave: boolean;
const PID = fixture.project.id,
  AID = fixture.sources[0]?.asset_id ?? "";
const SES = "ses_01JCBQ00000000000000000002";
const state = () => ({
  document: structuredClone(document),
  revision,
  recovery: null,
  sources: [{ asset_id: AID, state: "available_unverified" }],
});
beforeEach(() => {
  resetWorkspaces();
  resetQueries();
  resetJobs();
  revision = 1;
  failSave = false;
  document = structuredClone(load("editor-project", fixture));
  host = createHost();
  install(host, { invoke, listen });
  host.route(`GET /v1/projects/${PID}`, () => state());
  host.route(`PUT /v1/projects/${PID}`, (body: unknown) => {
    if (failSave)
      throw { code: "worker.unavailable", message: "Worker unavailable", retryable: true };
    const request = body as { document: EditorProject; expected_revision: number };
    if (request.expected_revision !== revision)
      throw { code: "project.revision_conflict", message: "A newer save exists", retryable: false };
    document = structuredClone(load("editor-project", request.document));
    revision++;
    return state();
  });
  host.route(
    `GET /v1/assets/${AID}`,
    asset({ id: AID, sha256: "a".repeat(64), duration_ms: 120000, original_name: "clip.mp4" }),
  );
  host.route(`GET /v1/assets/${AID}/derived`, {
    asset_id: AID,
    artifacts: [
      { kind: "proxy", status: "ready" },
      { kind: "filmstrip", status: "ready", filmstrip: { times_ms: [15000, 30000, 55000] } },
    ],
  });
  host.route("GET /v1/projects?offset=0&limit=50", () => ({
    items: [
      {
        id: PID,
        title: document.project.title,
        session_id: SES,
        updated_at: document.project.updated_at,
        revision,
      },
    ],
    total: 1,
    offset: 0,
  }));
  host.route("GET /v1/jobs?limit=200", []);
  host.route("GET /v1/profiles", []);
  // Export (M24): one CPU encoder and a preset; no renders yet.
  host.route("GET /v1/render/presets", [
    {
      schema_version: "1.18",
      id: "horizontal-720p30",
      display_name: "Horizontal 720p, 30 fps",
      width: 1280,
      height: 720,
      fps: { num: 30, den: 1 },
      video: { codec: "h264", crf: 23 },
      audio: { codec: "aac", bitrate_kbps: 160, sample_rate_hz: 48000 },
    },
  ]);
  host.route("GET /v1/render/encoders", {
    schema_version: "1.18",
    ffmpeg_version: "7.1.1",
    encoders: [{ id: "libx264", label: "CPU (libx264)", kind: "cpu", available: true }],
  });
  host.route(`GET /v1/projects/${PID}/renders`, []);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(async function (
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, "paused", { value: false, configurable: true });
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, "paused", { value: true, configurable: true });
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  window.location.hash = `#/project/${PID}`;
});
afterEach(() => {
  cleanup();
  resetWorkspaces();
  resetQueries();
  resetJobs();
  vi.restoreAllMocks();
});
const editor = () => render(<EditorView id={PID} workerReady />);
async function ready() {
  await screen.findByRole("heading", { name: fixture.project.title });
  await screen
    .findByRole("button", { name: "Play" })
    .then((b) => waitFor(() => expect(b.hasAttribute("disabled")).toBe(false)));
}
async function numeric(label: string, value: number) {
  fireEvent.change(screen.getByLabelText(label), { target: { value: String(value) } });
}

it("loads a single primary track with source boundaries, filmstrip, labelled trim alternatives and aspect placeholder", async () => {
  editor();
  await ready();
  expect(screen.getByRole("heading", { name: "Primary track" })).toBeTruthy();
  expect(screen.getAllByRole("button", { name: /clip.mp4/ }).length).toBe(2);
  expect(screen.getByLabelText("In trim handle")).toBeTruthy();
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(12500));
  fireEvent.change(screen.getByLabelText("Preview aspect ratio"), { target: { value: "9:16" } });
  expect(screen.getByRole("group", { name: "Project preview" }).getAttribute("data-aspect")).toBe(
    "9:16",
  );
  expect(screen.getByRole("status", { name: "Project save status" }).textContent).toContain(
    "Unsaved",
  );
  // M24 adds rendering: the Export panel renders the saved revision.
  expect(screen.getByRole("heading", { name: "Export" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Render" })).toBeTruthy();
});
it("keyboard-only numeric trim/split/reorder/remove and undo/redo are command-backed and autosave/reload", async () => {
  const user = userEvent.setup();
  let view = editor();
  await ready();
  const input = screen.getByLabelText("Source in (ms)");
  input.focus();
  await user.clear(input);
  await user.type(input, "13000");
  await user.keyboard("{Enter}");
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(13000));
  const offset = screen.getByLabelText("Split offset in cut (ms)");
  offset.focus();
  await user.clear(offset);
  await user.type(offset, "1000");
  await user.keyboard("{Enter}");
  expect(screen.getAllByRole("button", { name: /clip.mp4/ })).toHaveLength(3);
  const move = screen.getByRole("button", { name: "Move later" });
  move.focus();
  await user.keyboard("{Enter}");
  const ws = await openWorkspace(PID);
  expect(ws.document.project.tracks[0]?.segments[1]?.source_in_ms).toBe(13000);
  const remove = screen.getByRole("button", { name: "Remove selected cut" });
  remove.focus();
  await user.keyboard("{Enter}");
  expect(screen.getAllByRole("button", { name: /clip.mp4/ })).toHaveLength(2);
  const section = screen.getByRole("heading", { name: fixture.project.title }).closest("section");
  if (!section) throw new Error("editor");
  section.focus();
  await user.keyboard("{Control>}z{/Control}");
  expect(screen.getAllByRole("button", { name: /clip.mp4/ })).toHaveLength(3);
  await user.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
  expect(screen.getAllByRole("button", { name: /clip.mp4/ })).toHaveLength(2);
  await user.keyboard("{Control>}s{/Control}");
  await waitFor(() =>
    expect(screen.getByRole("status", { name: "Project save status" }).textContent).toContain(
      "Saved",
    ),
  );
  const saved = structuredClone(document);
  view.unmount();
  resetWorkspaces();
  view = editor();
  await ready();
  expect((await openWorkspace(PID)).document).toEqual(saved);
  view.unmount();
});
it("does not invoke editing shortcuts while typing and rejects invalid trim without losing draft values", async () => {
  editor();
  await ready();
  const before = (await openWorkspace(PID)).document;
  const input = screen.getByLabelText("Source in (ms)");
  input.focus();
  fireEvent.keyDown(input, { key: "Delete" });
  expect((await openWorkspace(PID)).document).toEqual(before);
  await numeric("Source in (ms)", 50000);
  fireEvent.submit(
    screen.getByRole("button", { name: "Apply trim" }).closest("form") as HTMLFormElement,
  );
  expect(screen.getByRole("alert").textContent).toContain("whole milliseconds");
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(50000));
  expect((await openWorkspace(PID)).document).toEqual(before);
});
it("handle commits are undoable and pointer cancellation leaves the project untouched", async () => {
  editor();
  await ready();
  const handle = screen.getByLabelText("In trim handle");
  fireEvent.change(handle, { target: { value: "14000" } });
  fireEvent.pointerCancel(handle);
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(12500));
  fireEvent.change(handle, { target: { value: "14000" } });
  fireEvent.pointerUp(handle);
  expect((await openWorkspace(PID)).document.project.tracks[0]?.segments[0]?.source_in_ms).toBe(
    14000,
  );
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(12500));
});
it("retains failed saves across navigation and worker restart, with copyable recovery JSON", async () => {
  failSave = true;
  const view = render(<App />);
  await ready();
  await numeric("Source in (ms)", 14000);
  fireEvent.click(screen.getByRole("button", { name: "Apply trim" }));
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await screen.findByRole("button", { name: "Retry save" });
  fireEvent.click(screen.getByRole("button", { name: "Show recovery JSON" }));
  const raw = screen.getByLabelText("Unsaved project JSON") as HTMLTextAreaElement;
  expect(JSON.parse(raw.value).project.tracks[0].segments[0].source_in_ms).toBe(14000);
  await act(async () =>
    host.emit("worker://status", { status: "restarting", attempt: 1, reason: "crash" }),
  );
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(14000));
  window.location.hash = "#/projects";
  fireEvent(window, new HashChangeEvent("hashchange"));
  await screen.findByRole("heading", { name: "Your projects" });
  expect(screen.getByRole("region", { name: "Unsaved drafts" })).toBeTruthy();
  window.location.hash = `#/project/${PID}`;
  fireEvent(window, new HashChangeEvent("hashchange"));
  await screen.findByLabelText("Source in (ms)");
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(14000));
  failSave = false;
  await act(async () =>
    host.emit("worker://status", { status: "ready", port: 1, pid: 2, restarts: 1 }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry save" }));
  await waitFor(() =>
    expect(screen.getByRole("status", { name: "Project save status" }).textContent).toContain(
      "Saved",
    ),
  );
  view.unmount();
});
it("does not overwrite a newer revision; keeps unsaved edits for recovery", async () => {
  editor();
  await ready();
  revision = 10;
  await numeric("Source in (ms)", 15000);
  fireEvent.click(screen.getByRole("button", { name: "Apply trim" }));
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await screen.findByRole("button", { name: "Retry save" });
  expect(screen.getByRole("alert").textContent).toContain("newer save");
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(15000));
  expect(document.project.tracks[0]?.segments[0]?.source_in_ms).toBe(12500);
});
it("blocks unresolved/hash-mismatched sources and keeps controls and edits available", async () => {
  const source = document.sources[0];
  if (source) source.requires_relink = true;
  editor();
  await screen.findByRole("heading", { name: fixture.project.title });
  expect(screen.getByRole("button", { name: "Play" })).toHaveProperty("disabled", true);
  expect(screen.getByText("Choose a verified source binding before previewing.")).toBeTruthy();
  await numeric("Source in (ms)", 14000);
  fireEvent.click(screen.getByRole("button", { name: "Apply trim" }));
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", String(14000));
});
it("autosave status changes do not pause or remap an actively playing preview", async () => {
  editor();
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "Play" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy());
  const ws = await openWorkspace(PID);
  await act(async () => {
    await ws.refreshSources();
  });
  expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
});
it("creates from a current session selection, preserves fields on stale selection error and supports cancellation", async () => {
  host.route(`GET /v1/sessions/${SES}/project-selection`, {
    layout_key: "a".repeat(64),
    duration_ms: 120000,
  });
  let fail = true;
  host.route(`POST /v1/sessions/${SES}/projects`, () => {
    if (fail)
      throw { code: "project.stale_session", message: "Session layout changed", retryable: false };
    return state();
  });
  render(<CreateProject sessionId={SES} currentMs={5000} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose range to edit" }));
  await screen.findByDisplayValue("120000");
  fireEvent.click(screen.getByRole("button", { name: "Use playhead as in" }));
  fireEvent.click(screen.getByRole("button", { name: "Create and edit" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Session in (ms)")).toHaveProperty("value", String(5000));
  fireEvent.click(screen.getByRole("button", { name: "Cancel selection" }));
  expect(screen.queryByLabelText("Session in (ms)")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Choose range to edit" }));
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Create and edit" }));
  await waitFor(() => expect(window.location.hash).toBe(`#/project/${PID}`));
  expect((host.posts(`/v1/sessions/${SES}/projects`)[1] as { start_ms: number }).start_ms).toBe(
    5000,
  );
});
it("projects page handles empty, error and retry states", async () => {
  host.route("GET /v1/projects?offset=0&limit=50", () => {
    throw { code: "worker.unavailable", message: "Offline", retryable: true };
  });
  render(<ProjectsView workerReady />);
  await screen.findByRole("alert");
  host.route("GET /v1/projects?offset=0&limit=50", { items: [], total: 0, offset: 0 });
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText(/No projects yet/);
});

it("keyboard help and skip-to-content preserve the project hash and unsaved work", async () => {
  render(<App />);
  await ready();
  const hash = window.location.hash;
  fireEvent.click(screen.getByRole("button", { name: "Keyboard help" }));
  expect(window.location.hash).toBe(hash);
  expect(screen.getByText("Editor keyboard shortcuts").closest("details")?.open).toBe(true);
  fireEvent.click(screen.getByRole("link", { name: "Skip to content" }));
  expect(window.location.hash).toBe(hash);
});
it("drag reordering uses the same reversible command as the keyboard controls", async () => {
  editor();
  await ready();
  const ws = await openWorkspace(PID);
  const before = ws.document.project.tracks[0]?.segments.map((s) => s.id);
  const buttons = screen.getAllByRole("button", { name: /clip.mp4/ });
  const first = buttons[0]?.closest(".editor-cut"),
    second = buttons[1]?.closest(".editor-cut");
  if (!first || !second) throw new Error("fixture cuts");
  fireEvent.dragStart(first, { dataTransfer: { setData: vi.fn(), effectAllowed: "move" } });
  fireEvent.dragOver(second);
  fireEvent.drop(second);
  expect(ws.document.project.tracks[0]?.segments.map((s) => s.id)).toEqual(
    [...(before ?? [])].reverse(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(ws.document.project.tracks[0]?.segments.map((s) => s.id)).toEqual(before);
});

it("exposes frozen project snapshots so view code cannot bypass M21 commands", async () => {
  editor();
  await ready();
  const workspace = await openWorkspace(PID);
  expect(() => {
    workspace.document.project.title = "Bypass";
  }).toThrow();
  expect(workspace.document.project.title).toBe(fixture.project.title);
});

it("caption correction, mute/gain, burn-in and sidecar state survive autosave and reload", async () => {
  const user = userEvent.setup();
  let view = editor();
  await ready();
  const text = screen.getByLabelText("Caption text");
  text.focus();
  await user.clear(text);
  await user.type(text, "Café & bridge\n你好 🚗");
  screen.getByRole("button", { name: "Apply caption" }).focus();
  await user.keyboard("{Enter}");
  screen.getByRole("button", { name: "Mute selected cut" }).focus();
  await user.keyboard("{Enter}");
  fireEvent.change(screen.getByLabelText("Project gain (dB)"), { target: { value: "6" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply project gain" }));
  fireEvent.click(screen.getByLabelText("Burn captions into future renders"));
  await user.selectOptions(screen.getByLabelText("Sidecar output"), "both");
  const ws = await openWorkspace(PID);
  await act(async () => {
    await ws.flush();
  });
  const saved = structuredClone(ws.document);
  expect(saved.project.audio.mute_ranges[0]?.start_ms).toBe(0);
  expect(saved.project.audio.gain_db).toBe(6);
  expect(saved.project.caption_settings?.sidecar).toBe("both");
  expect(saved.project.captions[0]?.text).toBe("Café & bridge\n你好 🚗");
  view.unmount();
  resetWorkspaces();
  resetQueries();
  view = editor();
  await ready();
  expect(screen.getByLabelText("Caption text")).toHaveProperty("value", "Café & bridge\n你好 🚗");
  expect(screen.getByLabelText("Burn captions into future renders")).toHaveProperty(
    "checked",
    true,
  );
  expect(screen.getByLabelText("Sidecar output")).toHaveProperty("value", "both");
  expect(screen.getByLabelText("Audio at playhead").textContent).toBe("Muted");
  view.unmount();
});
it("sidecar save cancellation/failure preserves project and exports only explicit plain text", async () => {
  editor();
  await ready();
  fireEvent.change(screen.getByLabelText("Sidecar output"), { target: { value: "both" } });
  const original = invoke.getMockImplementation();
  let fail = false;
  let exported = "";
  invoke.mockImplementation((command: string, args?: Record<string, unknown>) => {
    if (command === "caption_export") {
      exported = String(args?.text);
      return fail
        ? Promise.reject({
            code: "caption.export_failed",
            message: "Choose a new filename",
            retryable: true,
          })
        : Promise.resolve(false);
    }
    return original?.(command, args);
  });
  const ws = await openWorkspace(PID),
    before = structuredClone(ws.document);
  fireEvent.click(screen.getByRole("button", { name: "Save VTT sidecar…" }));
  await screen.findByText(/Sidecar save cancelled/);
  expect(exported).toContain("WEBVTT");
  expect(ws.document).toEqual(before);
  fail = true;
  fireEvent.click(screen.getByRole("button", { name: "Save SRT sidecar…" }));
  await screen.findByText(/Choose a new filename/);
  expect(ws.document).toEqual(before);
});
it("warns about configured HUD conflicts and does not apply editor shortcuts to caption text", async () => {
  const profile = {
    schema_version: "1.9",
    id: "safe-hud",
    profile_version: "1.0.0",
    display_name: "HUD test",
    game_family: "generic",
    license: "Apache-2.0",
    capabilities: [],
    frame: { aspect_ratios: ["16:9"], min_width: 64, min_height: 36 },
    regions: { hud: [0, 0, 1, 0.3] },
    safe_zones: { preserve: ["hud"] },
    detectors: [],
  };
  host.route("GET /v1/profiles", [
    {
      id: profile.id,
      profile_version: profile.profile_version,
      display_name: profile.display_name,
    },
  ]);
  host.route("GET /v1/profiles/safe-hud/calibration", { effective: profile });
  editor();
  await ready();
  await waitFor(() =>
    expect(screen.getByLabelText("Protected HUD/subtitle profile").textContent).toContain(
      "HUD test",
    ),
  );
  fireEvent.change(screen.getByLabelText("Protected HUD/subtitle profile"), {
    target: { value: "safe-hud" },
  });
  await screen.findByText(/overlaps protected regions: hud/);
  const ws = await openWorkspace(PID),
    before = ws.document.project.tracks[0]?.segments.length;
  const user = userEvent.setup();
  screen.getByLabelText("Caption text").focus();
  await user.keyboard("s{Delete}");
  expect(ws.document.project.tracks[0]?.segments.length).toBe(before);
  fireEvent.change(screen.getByLabelText("Caption placement"), { target: { value: "bottom" } });
  expect(screen.queryByText(/overlaps protected regions/)).toBeNull();
});
it("cancelled transcript loading and a concurrent edit cannot replace caption drafts", async () => {
  let resolve: (value: unknown) => void = () => undefined;
  host.route(
    `GET /v1/sessions/${SES}/transcript`,
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  editor();
  await ready();
  fireEvent.click(screen.getByLabelText("Replace existing captions"));
  fireEvent.click(screen.getByRole("button", { name: "Use session transcript" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel transcript loading" }));
  await act(async () => resolve({ schema_version: "1.13", session_id: SES, segments: [] }));
  const ws = await openWorkspace(PID);
  expect(ws.document.project.captions[0]?.text).toBe("Here we go");
  fireEvent.click(screen.getByRole("button", { name: "Use session transcript" }));
  fireEvent.click(screen.getByRole("button", { name: "Mute selected cut" }));
  await act(async () => resolve({ schema_version: "1.13", session_id: SES, segments: [] }));
  await screen.findByText(/project changed while loading/i);
  expect(ws.document.project.captions[0]?.text).toBe("Here we go");
});

it("caption and audio edits update preview without restarting the playing source", async () => {
  editor();
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "Play" }));
  await screen.findByRole("button", { name: "Pause" });
  fireEvent.click(screen.getByRole("button", { name: "Mute selected cut" }));
  expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Burn captions into future renders"));
  expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  expect(screen.getByLabelText("Audio at playhead").textContent).toBe("Muted");
});

it("typing an unapplied caption draft cancels a pending transcript replacement", async () => {
  let resolve: (value: unknown) => void = () => undefined;
  host.route(
    `GET /v1/sessions/${SES}/transcript`,
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  editor();
  await ready();
  fireEvent.click(screen.getByLabelText("Replace existing captions"));
  fireEvent.click(screen.getByRole("button", { name: "Use session transcript" }));
  const user = userEvent.setup(),
    text = screen.getByLabelText("Caption text");
  await user.clear(text);
  await user.type(text, "Unapplied local correction");
  await act(async () => resolve({ schema_version: "1.13", session_id: SES, segments: [] }));
  expect(screen.getByLabelText("Caption text")).toHaveProperty(
    "value",
    "Unapplied local correction",
  );
  await screen.findByText(/cancelled because fields changed/);
});

it("unapplied caption/trim fields survive audio commands while undo resets actual content changes", async () => {
  editor();
  await ready();
  fireEvent.change(screen.getByLabelText("Caption text"), { target: { value: "Local draft" } });
  await numeric("Source in (ms)", 13000);
  fireEvent.click(screen.getByRole("button", { name: "Mute selected cut" }));
  expect(screen.getByLabelText("Caption text")).toHaveProperty("value", "Local draft");
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", "13000");
  fireEvent.click(screen.getByRole("button", { name: "Apply caption" }));
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByLabelText("Caption text")).toHaveProperty("value", "Here we go");
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", "13000");
  fireEvent.click(screen.getByRole("button", { name: "Apply trim" }));
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByLabelText("Source in (ms)")).toHaveProperty("value", "12500");
});
