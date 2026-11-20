// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobCenter } from "./JobCenter";
import { reloadJobs, resetJobs, upsertJob, useJobFeed, useJobs } from "./jobs";
import { resetQueries } from "./query";
import { createHost, type FakeHost, install, job, must } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

let host: FakeHost;

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetJobs();
  resetQueries();
});

describe("job center", () => {
  it("shows loading, then an empty list", async () => {
    host.route("GET /v1/jobs?limit=200", []);
    render(<JobCenter onClose={() => undefined} />);
    expect(screen.getByRole("status").textContent).toBe("Loading jobs…");
    await act(reloadJobs);
    expect(screen.getByText("No background jobs yet.")).toBeTruthy();
  });

  it("explains a load error and retries", async () => {
    host.route("GET /v1/jobs?limit=200", () => {
      throw { code: "worker.unavailable", message: "x", retryable: true };
    });
    const user = userEvent.setup();
    render(<JobCenter onClose={() => undefined} />);
    await act(reloadJobs);
    expect(screen.getByRole("alert").textContent).toMatch(/media worker is not running/);
    host.route("GET /v1/jobs?limit=200", []);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No background jobs yet.")).toBeTruthy();
  });

  it("cancels a running job and shows the durable state", async () => {
    const running = job({ kind: "proxy", state: "proxying", progress: { done: 250, total: 1000 } });
    host.route("GET /v1/jobs?limit=200", [running]);
    host.route(`POST /v1/jobs/${running.id}/cancel`, { ...running, state: "cancelled" });
    const user = userEvent.setup();
    render(<JobCenter onClose={() => undefined} />);
    await act(reloadJobs);
    const bar = screen.getByLabelText("Prepare playback progress") as HTMLProgressElement;
    expect(bar.value).toBe(25);
    await user.click(screen.getByRole("button", { name: "Cancel prepare playback" }));
    const row = await screen.findByRole("listitem", { name: "Prepare playback: Cancelled" });
    expect(within(row).getByText(/Nothing partial was kept/)).toBeTruthy();
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("says a cancelled model download keeps its partial", async () => {
    const cancelled = job({
      kind: "model_download",
      state: "cancelled",
      params: { name: "base.en" },
    });
    host.route("GET /v1/jobs?limit=200", [cancelled]);
    render(<JobCenter onClose={() => undefined} />);
    await act(reloadJobs);
    expect(screen.getByText(/partial download is kept so you can resume it/)).toBeTruthy();
    expect(screen.queryByText(/Nothing partial was kept/)).toBeNull();
  });

  it("keeps a finished state when a slower cancel reply still says running", () => {
    const running = job({ kind: "model_download", state: "analyzing", attempt: 1 });
    const { result } = renderHook(() => useJobs());
    act(() => upsertJob(running));
    act(() => upsertJob({ ...running, state: "cancelled" })); // live event
    act(() => upsertJob(running)); // stale reply to the cancel request
    expect(result.current.jobs[0]?.state).toBe("cancelled");
    act(() => upsertJob({ ...running, state: "queued", attempt: 2 })); // retry
    expect(result.current.jobs[0]?.state).toBe("queued");
  });

  it("retries only retryable failures and hides technical details by default", async () => {
    const retryable = job({
      kind: "proxy",
      state: "failed",
      error: {
        code: "derived.disk_full",
        message: "Disk full.",
        retryable: true,
        stderr_tail: "Error writing trailer: No space left on device",
      },
    });
    const permanent = job({
      kind: "import",
      state: "failed",
      error: { code: "media.damaged", message: "Damaged.", retryable: false },
    });
    host.route("GET /v1/jobs?limit=200", [retryable, permanent]);
    host.route(`POST /v1/jobs/${retryable.id}/retry`, {
      ...retryable,
      state: "queued",
      error: undefined,
    });
    const user = userEvent.setup();
    render(<JobCenter onClose={() => undefined} />);
    await act(reloadJobs);
    expect(
      screen.getByText("There is not enough free space where playback media is stored."),
    ).toBeTruthy();
    expect(screen.getByText("The file is damaged or incomplete.")).toBeTruthy();
    const details = must(screen.getByText("Technical details").closest("details"), "details");
    expect(details.open).toBe(false);
    expect(screen.queryByRole("button", { name: "Retry import" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Retry prepare playback" }));
    expect(await screen.findByRole("listitem", { name: "Prepare playback: Waiting" })).toBeTruthy();
  });

  it("summarizes an import, including files that were not imported", async () => {
    host.route("GET /v1/jobs?limit=200", [
      job({
        kind: "import",
        state: "ready",
        result: {
          schema_version: "1.6",
          mode: "reference",
          items: [
            {
              source: 0,
              relative_path: "a.mp4",
              outcome: "imported",
              asset_id: "ast_01JCBQ00000000000000000001",
            },
            {
              source: 0,
              relative_path: "b.mp4",
              outcome: "existing",
              asset_id: "ast_01JCBQ00000000000000000002",
            },
            {
              source: 0,
              relative_path: "broken.mp4",
              outcome: "failed",
              error: { code: "media.damaged", message: "x", retryable: false },
            },
          ],
          totals: { files: 3, imported: 1, existing: 1, relinked: 0, skipped: 0, failed: 1 },
        },
      }),
    ]);
    render(<JobCenter onClose={() => undefined} />);
    await act(reloadJobs);
    expect(screen.getByText("1 imported · 1 already in the library · 1 failed")).toBeTruthy();
    const failures = screen.getByRole("list", { name: "Files that were not imported" });
    expect(within(failures).getByText("broken.mp4")).toBeTruthy();
    expect(within(failures).getByText(/damaged or incomplete/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open the first imported clip" })).toBeTruthy();
  });

  it("follows live events and resynchronizes after missed ones", async () => {
    const running = job({ kind: "import", state: "probing" });
    host.route("GET /v1/jobs?limit=200", [running]);
    renderHook(() => useJobFeed(true));
    render(<JobCenter onClose={() => undefined} />);
    expect(await screen.findByRole("listitem", { name: "Import: Reading media" })).toBeTruthy();

    act(() =>
      host.emit("worker://job-event", {
        seq: 2,
        kind: "state",
        job: { ...running, state: "ready" },
      }),
    );
    expect(await screen.findByRole("listitem", { name: "Import: Done" })).toBeTruthy();

    const later = job({ kind: "proxy", state: "queued" });
    host.route("GET /v1/jobs?limit=200", [{ ...running, state: "ready" }, later]);
    act(() => host.emit("worker://resync", null));
    expect(await screen.findByRole("listitem", { name: "Prepare playback: Waiting" })).toBeTruthy();
  });
});
