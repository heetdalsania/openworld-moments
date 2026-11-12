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
it("shows capabilities with each status in words", async () => {
  render(<SystemPanel />);
  expect(await screen.findByText("Core checks passed")).toBeTruthy();
  expect(screen.getByText("Passed: codecs")).toBeTruthy();
  expect(screen.getByRole("region", { name: "System check" })).toBeTruthy();
});
it("explains failed checks and can run again", async () => {
  report = {
    ...report,
    ready: false,
    checks: [{ id: "codecs", status: "fail", message: "Repair the packaged FFmpeg" }],
  };
  render(<SystemPanel heading="This computer" />);
  expect(await screen.findByText(/Repair the packaged FFmpeg/)).toBeTruthy();
  expect(screen.getByText("Failed: codecs")).toBeTruthy();
  expect(screen.getByText("Repair the failed checks before importing")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Run system check again" }));
});
it("reports unavailable checks in Settings", async () => {
  host.route("GET /v1/system-doctor", () => {
    throw { message: "Worker unavailable", retryable: true };
  });
  render(<SystemPanel />);
  expect((await screen.findByRole("alert")).textContent).toContain("Worker unavailable");
});

function mac(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: "1.25",
    host_version: "0.1.0",
    os: { family: "macos", version: "15.2", minimum: "14.0" },
    architecture: { binary: "aarch64", translated: false },
    build: { target: "aarch64-apple-darwin", profile: "release", bundled_worker: false },
    support: { level: "development", reasons: ["macos-preview"] },
    directories: { convention: "macos-standard" },
    integrations: { file_manager: "finder", secret_store: "none", menus: "default" },
    ...overrides,
  };
}

it("names the Windows alpha build without extra notes", async () => {
  render(<SystemPanel />);
  expect(await screen.findByText("Windows · x64 build · version 0.1.0 · Alpha")).toBeTruthy();
  expect(screen.queryByText(/previews/)).toBeNull();
});

it("shows the Mac architecture and that macOS is a preview, even without a worker", async () => {
  host.platform = mac();
  host.route("GET /v1/system-doctor", () => {
    throw { message: "Worker unavailable", retryable: true };
  });
  render(<SystemPanel />);
  expect(
    await screen.findByText(
      "macOS 15.2 · Apple Silicon (arm64) build · version 0.1.0 · Development build",
    ),
  ).toBeTruthy();
  expect(screen.getByText(/macOS builds are previews/)).toBeTruthy();
  expect(screen.queryByRole("alert", { name: /Rosetta/ })).toBeNull();
});

it("warns when the Intel build runs under Rosetta", async () => {
  host.platform = mac({
    architecture: { binary: "x86_64", translated: true },
    build: { target: "x86_64-apple-darwin", profile: "release", bundled_worker: false },
    support: { level: "unsupported", reasons: ["macos-preview", "translated"] },
  });
  render(<SystemPanel />);
  expect(
    await screen.findByText(/Intel \(x86_64\) build · version 0.1.0 · Not supported/),
  ).toBeTruthy();
  const alerts = await screen.findAllByRole("alert");
  expect(
    alerts.some((a) => /Download the Apple Silicon \(arm64\) build/.test(a.textContent ?? "")),
  ).toBe(true);
});

it("ignores a platform report that breaks the contract", async () => {
  host.platform = mac({ data_dir: "/Users/someone" });
  render(<SystemPanel />);
  expect(await screen.findByText("Core checks passed")).toBeTruthy();
  expect(screen.queryByText(/Apple Silicon/)).toBeNull();
});
