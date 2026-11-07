// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CalibrationState } from "./api";
import { CalibrationView } from "./CalibrationView";
import { RoiCanvas } from "./RoiCanvas";
import type { Regions, ROI } from "./calibration";
import { resetQueries } from "./query";
import { asset, ASSET_ID, createHost, install, type FakeHost } from "./testing/fakeHost";
import manifest from "../../../profiles/generic-open-world/profile.json";
import { load } from "@openworld-moments/contracts";
const profile = load("profile", manifest);
const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
let host: FakeHost;
let state: CalibrationState;
const url = "/v1/profiles/generic-open-world";
beforeEach(() => {
  resetQueries();
  host = createHost();
  install(host, { invoke, listen });
  state = {
    base: structuredClone(profile),
    base_key: "a".repeat(64),
    effective: structuredClone(profile),
    patch: null,
    base_changed: false,
    conflict: null,
  } as CalibrationState;
  host.route("GET /v1/profiles", [
    {
      id: profile.id,
      display_name: profile.display_name,
      profile_version: profile.profile_version,
    },
  ]);
  host.route(`GET ${url}/calibration`, () => structuredClone(state));
  host.route("GET /v1/assets?order=newest&limit=60", []);
  host.route(`PUT ${url}/calibration`, (body: unknown) => {
    const regions = (body as { regions: Regions }).regions;
    state = {
      ...state,
      effective: { ...state.base, regions },
      patch: {
        schema_version: "1.10",
        profile_id: profile.id,
        base_version: "1.0.0",
        base_key: state.base_key,
        game_family: profile.game_family,
        frame: profile.frame,
        regions,
        provenance: { tool: "owm-calibration", version: "1", created_at: "2026-11-07T00:00:00Z" },
      },
    };
    return structuredClone(state);
  });
  host.route(`POST ${url}/reset`, () => {
    state = { ...state, effective: structuredClone(state.base), patch: null };
    return structuredClone(state);
  });
  host.route(`POST ${url}/patch`, (body: unknown) => {
    state = {
      ...state,
      patch: body as CalibrationState["patch"],
      effective: { ...state.base, regions: (body as { regions: Regions }).regions },
    };
    return structuredClone(state);
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
async function open() {
  const user = userEvent.setup();
  render(<CalibrationView />);
  await user.selectOptions(await screen.findByLabelText("Installed profile"), profile.id);
  await screen.findByRole("heading", { name: "Regions" });
  return user;
}
it("runs edit → save → export cancelled → import → reset, keeping export unavailable while dirty", async () => {
  const user = await open();
  expect(screen.getByText("Your library is empty. Import a clip first.")).toBeTruthy();
  await user.clear(screen.getByLabelText("X"));
  await user.type(screen.getByLabelText("X"), "0.15");
  expect(
    (screen.getByRole("button", { name: "Export saved patch…" }) as HTMLButtonElement).disabled,
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: "Save local overrides" }));
  await screen.findByText("Local overrides saved. Installed profile unchanged.");
  const patch = structuredClone(state.patch);
  invoke.mockImplementationOnce(() => Promise.resolve(false));
  await user.click(screen.getByRole("button", { name: "Export saved patch…" }));
  await screen.findByText("Patch export cancelled.");
  await user.click(screen.getByRole("button", { name: "Reset all to base" }));
  await screen.findByText("Reset to the current base profile.");
  expect((screen.getByLabelText("X") as HTMLInputElement).value).toBe("0.1");
  const file = new File([JSON.stringify(patch)], "patch.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve(JSON.stringify(patch)) });
  await user.upload(screen.getByLabelText("Import profile patch"), file);
  await screen.findByText("Profile patch imported and saved locally.");
  expect((screen.getByLabelText("X") as HTMLInputElement).value).toBe("0.15");
  expect(state.base.regions.signal).toEqual([0.1, 0.1, 0.8, 0.8]);
});
it("blocks invalid bounds, shows save failures, and allows custom names and reset", async () => {
  const user = await open();
  fireEvent.change(screen.getByLabelText("X"), { target: { value: "0.9" } });
  expect(screen.getByRole("alert").textContent).toContain("fit entirely");
  expect(
    (screen.getByRole("button", { name: "Save local overrides" }) as HTMLButtonElement).disabled,
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: "Reset selected to base" }));
  await user.type(screen.getByLabelText("New region name"), "subtitle");
  await user.click(screen.getByRole("button", { name: "Add region" }));
  expect((screen.getByLabelText("Selected region") as HTMLSelectElement).value).toBe("subtitle");
  host.route(`PUT ${url}/calibration`, () => {
    throw { message: "Profile changed; reload.", code: "profile.invalid", retryable: false };
  });
  await user.click(screen.getByRole("button", { name: "Save local overrides" }));
  expect((await screen.findByRole("alert")).textContent).toContain("reload");
  expect((screen.getByLabelText("Selected region") as HTMLSelectElement).value).toBe("subtitle");
  await user.click(screen.getByRole("button", { name: "Remove custom region" }));
  expect((screen.getByLabelText("Selected region") as HTMLSelectElement).value).toBe("signal");
});
it("rejects media-bearing import before sending it to the worker", async () => {
  const user = await open();
  const file = new File(["{}"], "bad.json", { type: "application/json" });
  Object.defineProperty(file, "text", {
    value: () => Promise.resolve(JSON.stringify({ frame_image: "private" })),
  });
  await user.upload(screen.getByLabelText("Import profile patch"), file);
  expect((await screen.findByRole("alert")).textContent).toContain("schema_version");
  expect(host.posts(`${url}/patch`)).toHaveLength(0);
});
it("shows loading, catalog error/retry, no installed profiles and profile update conflicts", async () => {
  host.route("GET /v1/profiles", () => {
    throw new Error("Catalog unavailable");
  });
  const user = userEvent.setup();
  render(<CalibrationView />);
  expect(screen.getByText("Loading profiles…")).toBeTruthy();
  await screen.findByText("Catalog unavailable");
  host.route("GET /v1/profiles", []);
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("No profiles are installed.");
  cleanup();
  resetQueries();
  state.base_changed = true;
  state.conflict = "Compatibility changed";
  host.route("GET /v1/profiles", [
    { id: profile.id, display_name: profile.display_name, profile_version: "1.1.0" },
  ]);
  render(<CalibrationView />);
  await user.selectOptions(await screen.findByLabelText("Installed profile"), profile.id);
  await screen.findByText(/Compatibility changed/);
  expect(screen.getByText(/Overrides are retained/)).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "Save local overrides" }) as HTMLButtonElement).disabled,
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: "Reset all to base" }));
});
it("prepares missing media, reports cancel guidance, captures decode failures and clears a frame", async () => {
  host.route("GET /v1/assets?order=newest&limit=60", [asset()]);
  host.route(`GET /v1/assets/${ASSET_ID}/derived`, { artifacts: [] });
  host.route(`POST /v1/assets/${ASSET_ID}/derived`, {});
  const user = await open();
  await user.selectOptions(screen.getByLabelText("Imported clip"), ASSET_ID);
  await user.click(await screen.findByRole("button", { name: "Prepare playback copy" }));
  await screen.findByText(/Cancel control/);
  host.route(`GET /v1/assets/${ASSET_ID}/derived`, {
    artifacts: [{ kind: "proxy", status: "ready" }],
  });
  await user.click(screen.getByRole("button", { name: "Check again" }));
  await waitFor(() => expect(document.querySelector("video")).toBeTruthy());
  const video = document.querySelector("video");
  if (!video) throw new Error("no video");
  fireEvent.canPlay(video);
  await user.selectOptions(screen.getByLabelText("Imported clip"), ASSET_ID);
  expect(
    (screen.getByRole("button", { name: "Capture this frame" }) as HTMLButtonElement).disabled,
  ).toBe(false);
  await user.click(screen.getByRole("button", { name: "Capture this frame" }));
  await screen.findByText(/This frame could not be read/);
  await user.click(screen.getByRole("button", { name: "Clear captured frame" }));
  await screen.findByText("Frame selection cleared.");
  fireEvent.error(video);
  await screen.findByText(/could not be decoded/);
});
it.each([
  [1280, 720],
  [1920, 1080],
  [3840, 2160],
  [1440, 1080],
  [1080, 1920],
])("keyboard moves and resizes precisely on %i × %i", async (width, height) => {
  const user = userEvent.setup();
  let last: Regions = {};
  const region: ROI = [0.25, 0.25, 0.5, 0.5];
  render(
    <RoiCanvas
      image="data:image/png;base64,"
      width={width}
      height={height}
      regions={{ signal: region }}
      base={{ signal: region }}
      selected="signal"
      name=""
      compare={true}
      onSelect={() => {}}
      onChange={(r) => {
        last = r;
      }}
    />,
  );
  const button = screen.getByRole("button", { name: "Region signal" });
  button.focus();
  await user.keyboard("{ArrowRight}");
  expect(last.signal?.[0]).toBe(0.25 + 1 / width);
  await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
  expect(last.signal?.[3]).toBe(0.5 + 1 / height);
  await user.keyboard("{Shift>}{ArrowLeft}{/Shift}");
  expect(last.signal?.[0]).toBe(0.25 - 10 / width);
});

it("shows saved overrides after navigating away and back, and can reload a changed base", async () => {
  const user = await open();
  fireEvent.change(screen.getByLabelText("X"), { target: { value: "0.15" } });
  await user.click(screen.getByRole("button", { name: "Save local overrides" }));
  await screen.findByText("Local overrides saved. Installed profile unchanged.");
  cleanup();
  render(<CalibrationView />);
  await user.selectOptions(await screen.findByLabelText("Installed profile"), profile.id);
  await screen.findByRole("heading", { name: "Regions" });
  expect((screen.getByLabelText("X") as HTMLInputElement).value).toBe("0.15");
  state = {
    ...state,
    base_key: "b".repeat(64),
    base: { ...state.base, profile_version: "1.1.0" },
    base_changed: true,
  };
  await user.click(
    screen.getByRole("button", { name: "Reload installed profile and saved overrides" }),
  );
  await screen.findByText(/Base 1.1.0/);
  expect(screen.getByText(/Overrides are retained/)).toBeTruthy();
});
