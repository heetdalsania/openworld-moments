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
  expect(screen.queryByRole("button", { name: /export|render/i })).toBeNull();
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
