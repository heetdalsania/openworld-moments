// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SystemDoctor } from "@openworld-moments/contracts";
import { SystemPanel } from "./SystemPanel";
import { resetQueries } from "./query";
import { createHost, install, type FakeHost } from "./testing/fakeHost";
const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
let host: FakeHost;
let report: SystemDoctor;
beforeEach(() => {
  localStorage.clear();
  host = createHost();
  install(host, { invoke, listen });
  report = {
    schema_version: "1.23",
    ready: true,
    packaged: true,
    platform: "Windows",
    architecture: "AMD64",
    free_bytes: 1e9,
    checks: [{ id: "codecs", status: "pass", message: "CPU codec test passed" }],
    tools: [{ name: "Python", version: "3.12.14", origin: "bundle", license: "PSF-2.0" }],
  };
  host.route("GET /v1/system-doctor", () => report);
});
afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  localStorage.clear();
});
it("shows first-run capabilities and retains an explicit acknowledgement", async () => {
  render(<SystemPanel firstRun />);
  expect(await screen.findByText("Core checks passed")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.queryByRole("region", { name: "System check" })).toBeNull();
  expect(localStorage.getItem("owm-system-check-0.1")).toBe("reviewed");
});
it("blocks Continue when required capabilities fail and displays repair guidance", async () => {
  report = {
    ...report,
    ready: false,
    checks: [{ id: "codecs", status: "fail", message: "Repair the packaged FFmpeg" }],
  };
  render(<SystemPanel firstRun />);
  expect(await screen.findByText(/Repair the packaged FFmpeg/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(
    true,
  );
});
it("reports unavailable checks in Settings", async () => {
  host.route("GET /v1/system-doctor", () => {
    throw { message: "Worker unavailable", retryable: true };
  });
  render(<SystemPanel />);
  expect((await screen.findByRole("alert")).textContent).toContain("Worker unavailable");
});
