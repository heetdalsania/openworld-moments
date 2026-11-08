// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { load, type PrivacyReview } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/moving-blur.json";
import reviewFixture from "../../../packages/contracts/fixtures/privacy-review/valid/unresolved.json";
import { PrivacyPanel } from "./PrivacyPanel";
import { ProjectWorkspace } from "./projectWorkspace";
import { resetQueries } from "./query";
import { createHost, install, type FakeHost } from "./testing/fakeHost";
const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
const doc = load("editor-project", fixture);
let workspace: ProjectWorkspace;
let host: FakeHost;
let report: PrivacyReview;
const save = vi.fn();
beforeEach(() => {
  report = structuredClone(reviewFixture) as PrivacyReview;
  report.project_id = doc.project.id;
  workspace = new ProjectWorkspace({ document: structuredClone(doc), revision: 1, recovery: null });
  host = createHost();
  install(host, { invoke, listen });
  host.route(`GET /v1/projects/${doc.project.id}/privacy-review`, () => report);
  host.route(`POST /v1/projects/${doc.project.id}/privacy-review`, (body: unknown) => {
    save(body);
    return report;
  });
});
afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  save.mockReset();
  resetQueries();
});
it("shows evidence, seeks, records deliberate dismissal and restores unresolved findings", async () => {
  const user = userEvent.setup(),
    seek = vi.fn();
  render(<PrivacyPanel workspace={workspace} atMs={0} seek={seek} onCommand={vi.fn()} />);
  await screen.findByText(/Call 202-555-0186/);
  await user.click(screen.getByRole("button", { name: /phone ·/ }));
  expect(seek).toHaveBeenCalledWith(100);
  await user.selectOptions(screen.getByRole("combobox", { name: /Decision for phone/ }), "ignore");
  await user.click(screen.getByRole("checkbox", { name: /I reviewed this project/ }));
  await user.click(screen.getByRole("button", { name: "Save review decisions" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0]?.[0]).toEqual({
    token: report.token,
    decisions: [{ id: report.flags[0]?.id, state: "ignore" }],
    acknowledged: true,
  });
  await user.selectOptions(
    screen.getByRole("combobox", { name: /Decision for phone/ }),
    "unresolved",
  );
  await user.click(screen.getByRole("button", { name: "Save review decisions" }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect((save.mock.calls[1]?.[0] as { decisions: { state: string }[] }).decisions[0]?.state).toBe(
    "unresolved",
  );
  expect(
    (screen.getByRole("button", { name: "Delete derived text" }) as HTMLButtonElement).disabled,
  ).toBe(true);
});
it("adds a manual blur with numeric keyframes through the editor command model", async () => {
  const user = userEvent.setup(),
    command = vi.fn();
  render(<PrivacyPanel workspace={workspace} atMs={700} seek={vi.fn()} onCommand={command} />);
  await user.click(screen.getByText("Manual moving blur regions"));
  await user.click(screen.getByRole("button", { name: "Draft a blur at playhead" }));
  await user.click(screen.getByRole("button", { name: "Add keyframe at playhead" }));
  await user.click(screen.getByRole("button", { name: "Apply blur regions" }));
  expect(command).toHaveBeenCalledWith(
    expect.objectContaining({
      kind: "settings",
      overlays: expect.arrayContaining([expect.objectContaining({ kind: "blur", start_ms: 700 })]),
    }),
  );
});

it("fetches fresh findings after a flush changes the revision during configuration", async () => {
  const user = userEvent.setup();
  const props = { workspace, atMs: 0, seek: vi.fn(), onCommand: vi.fn() };
  const view = render(<PrivacyPanel {...props} />);
  await screen.findByText(/Call 202-555-0186/);
  const revision = vi.spyOn(workspace.autosave, "revision", "get");
  vi.spyOn(workspace, "flush").mockImplementation(async () => {
    revision.mockReturnValue(2);
    view.rerender(<PrivacyPanel {...props} />);
    await Promise.resolve();
  });
  host.route(`PUT /v1/projects/${doc.project.id}/privacy-review`, () => {
    const original = report.flags[0];
    if (!original) throw new Error("flag fixture");
    report = {
      ...report,
      revision: 2,
      token: "c".repeat(64),
      config: { labels: ["finale"], ranges: [] },
      flags: [...report.flags, { ...original, id: "d".repeat(64), category: "spoiler" }],
    };
    return report;
  });
  await user.click(screen.getByText("Spoiler labels and ranges", { exact: true }));
  await user.type(screen.getByRole("textbox", { name: "Spoiler labels (one per line)" }), "finale");
  await user.click(screen.getByRole("button", { name: "Save spoiler configuration" }));
  expect(
    await screen.findByRole("combobox", { name: "Decision for spoiler at 100 ms" }),
  ).toBeTruthy();
  revision.mockRestore();
});

it("disables stale choices and range actions until the current draft is saved and rescanned", async () => {
  workspace.status = "unsaved";
  render(<PrivacyPanel workspace={workspace} atMs={0} seek={vi.fn()} onCommand={vi.fn()} />);
  const select = await screen.findByRole("combobox", { name: /Decision for phone/ });
  expect(select.closest("fieldset")?.disabled).toBe(true);
  expect(
    screen.getByRole("button", { name: "Save review decisions" }).closest("fieldset")?.disabled,
  ).toBe(true);
});

it("retains a saved checklist acknowledgment while a finding remains unresolved", async () => {
  report.summary.acknowledged = true;
  render(<PrivacyPanel workspace={workspace} atMs={0} seek={vi.fn()} onCommand={vi.fn()} />);
  const check = await screen.findByRole("checkbox", { name: /^I reviewed this project/ });
  expect((check as HTMLInputElement).checked).toBe(true);
  expect(screen.getByText(/Export review is required/)).toBeTruthy();
});
