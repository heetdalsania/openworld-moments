// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ModelManager as Status } from "@openworld-moments/contracts";
import { ModelManager } from "./ModelManager";
import { resetJobs, upsertJob } from "./jobs";
import { resetQueries } from "./query";
import { createHost, install, job, type FakeHost } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
let host: FakeHost;
let status: Status;
const sha = "a".repeat(64);
beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  status = {
    schema_version: "1.23",
    catalog_version: 1,
    models: [
      {
        name: "tiny.en",
        revision: "b".repeat(40),
        size_bytes: 4096,
        sha256: sha,
        license: "MIT",
        source_url: "https://huggingface.co/ggerganov/whisper.cpp",
        downloaded_bytes: 0,
        disk_required_bytes: 67117056,
        active_sha256: null,
        versions: [],
      },
    ],
  };
  host.route("GET /v1/model-manager", () => structuredClone(status));
  host.route("POST /v1/model-manager/download", () =>
    job({ kind: "model_download", params: { name: "tiny.en", sha256: sha }, state: "queued" }),
  );
  host.route("POST /v1/model-manager/remove", () => {
    status.models[0] = {
      ...(status.models[0] as Status["models"][number]),
      active_sha256: null,
      versions: [],
    };
    return status;
  });
});
afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetJobs();
  resetQueries();
});

it("lists metadata without downloading, then installs only on explicit action and refreshes verified status", async () => {
  render(<ModelManager />);
  const installButton = await screen.findByRole("button", { name: "Install tiny.en" });
  expect(invoke.mock.calls.some((c) => c[1]?.method === "POST")).toBe(false);
  expect(screen.getByText(/Models are pinned to the signed catalog/)).toBeTruthy();
  installButton.focus();
  await userEvent.keyboard("{Enter}");
  expect(await screen.findByRole("button", { name: "Cancel tiny.en" })).toBeTruthy();
  status.models[0] = {
    ...(status.models[0] as Status["models"][number]),
    active_sha256: sha,
    versions: [sha],
  };
  await act(async () =>
    upsertJob(job({ kind: "model_download", params: { name: "tiny.en" }, state: "ready" })),
  );
  expect(await screen.findByText(/Verified installed/)).toBeTruthy();
});

it("reports resumable bytes and a failed download without claiming installation", async () => {
  status.models[0] = { ...(status.models[0] as Status["models"][number]), downloaded_bytes: 1000 };
  upsertJob(
    job({
      kind: "model_download",
      state: "failed",
      params: { name: "tiny.en" },
      error: { code: "models.corrupt", message: "Checksum mismatch", retryable: true },
    }),
  );
  render(<ModelManager />);
  expect(await screen.findByRole("button", { name: "Resume install tiny.en" })).toBeTruthy();
  expect(screen.getByText(/Checksum mismatch/)).toBeTruthy();
  expect(screen.queryByText(/Verified installed/)).toBeNull();
});

it("requires a separate confirmation to remove models", async () => {
  status.models[0] = {
    ...(status.models[0] as Status["models"][number]),
    active_sha256: sha,
    versions: [sha],
  };
  render(<ModelManager />);
  await userEvent.click(await screen.findByRole("button", { name: "Remove tiny.en…" }));
  expect(invoke.mock.calls.some((c) => c[1]?.path === "/v1/model-manager/remove")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "Confirm remove tiny.en" }));
  expect(await screen.findByRole("button", { name: "Install tiny.en" })).toBeTruthy();
});

it("shows a catalog verification failure and offers retry", async () => {
  host.route("GET /v1/model-manager", () => {
    throw { code: "models.catalog_invalid", message: "Repair the signed catalog", retryable: true };
  });
  render(<ModelManager />);
  expect((await screen.findByRole("alert")).textContent).toContain("Repair the signed catalog");
  expect(screen.queryByRole("button", { name: "Install tiny.en" })).toBeNull();
});
