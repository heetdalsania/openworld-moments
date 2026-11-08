// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { load } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { LayoutPanel } from "./LayoutPanel";
import { applyCommand, type EditorCommand } from "./editor";
import { resetQueries } from "./query";
import { createHost, install } from "./testing/fakeHost";
const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
beforeEach(() => {
  const host = createHost();
  install(host, { invoke, listen });
  host.route("GET /v1/profiles", () => []);
});
afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
});
it("edits a fixed crop and keys by keyboard, resets and preserves unrelated drafts", async () => {
  const user = userEvent.setup();
  let doc = load("editor-project", structuredClone(fixture));
  const cut = () => required(required(doc.project.tracks[0]).segments[0]);
  const props = () => ({
    document: doc,
    cut: cut(),
    width: 1920,
    height: 1080,
    atMs: 0,
    seek: vi.fn(),
    onCommand: (c: EditorCommand) => {
      doc = applyCommand(doc, c);
    },
  });
  const view = render(<LayoutPanel {...props()} />);
  expect(screen.getByText(/protected HUD regions are unknown/)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Set 9:16 crop fields" }));
  await user.click(screen.getByRole("button", { name: "Apply fixed crop" }));
  expect(required(cut().vertical_crop).strategy).toBe("fixed");
  view.rerender(<LayoutPanel {...props()} />);
  const left = screen.getByRole("spinbutton", { name: "Crop left" });
  await user.clear(left);
  await user.type(left, "0.1");
  doc = applyCommand(doc, { kind: "audio", operation: { action: "project-gain", gain_db: -6 } });
  view.rerender(<LayoutPanel {...props()} />);
  expect((left as HTMLInputElement).value).toBe("0.1");
  const time = screen.getByRole("spinbutton", { name: "Key time in cut (ms)" });
  await user.clear(time);
  await user.type(time, "500");
  await user.click(screen.getByRole("button", { name: "Add or replace keyframe" }));
  expect(required(cut().vertical_crop).keyframes).toHaveLength(2);
  view.rerender(<LayoutPanel {...props()} />);
  await user.click(screen.getByRole("button", { name: "Reset vertical layout" }));
  expect(required(cut().vertical_crop).strategy).toBe("fit");
});
it("makes a missing-profile suggestion explicit, versioned and replaceable", async () => {
  const user = userEvent.setup();
  let doc = load("editor-project", structuredClone(fixture));
  render(
    <LayoutPanel
      document={doc}
      cut={required(doc.project.tracks[0]).segments[0]}
      width={1920}
      height={1080}
      atMs={0}
      seek={vi.fn()}
      onCommand={(c) => {
        doc = applyCommand(doc, c);
      }}
    />,
  );
  expect(required(required(doc.project.tracks[0]).segments[0]).vertical_crop).toBeUndefined();
  await user.click(screen.getByRole("button", { name: "Use framing suggestion" }));
  expect(
    required(required(required(doc.project.tracks[0]).segments[0]).vertical_crop).suggestion,
  ).toMatchObject({
    algorithm: "static-profile/1",
    confidence: 0.25,
  });
});

function required<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error("Missing fixture value");
  return value;
}
