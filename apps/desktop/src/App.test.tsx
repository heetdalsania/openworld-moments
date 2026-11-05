// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

type Listener = (event: { payload: unknown }) => void;
let statusListener: Listener | undefined;

function mockHost(appInfo: Promise<unknown>, worker: unknown) {
  invoke.mockImplementation((cmd: string) =>
    cmd === "app_info" ? appInfo : Promise.resolve(worker),
  );
  listen.mockImplementation((_name: string, cb: Listener) => {
    statusListener = cb;
    return Promise.resolve(() => undefined);
  });
}

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  statusListener = undefined;
});

describe("App placeholder", () => {
  it("shows the planning-stage placeholder and host version", async () => {
    mockHost(Promise.resolve({ name: "OpenWorld Moments", version: "0.0.0", stage: "planning" }), {
      status: "starting",
    });
    render(<App />);

    expect(screen.getByRole("heading", { name: "OpenWorld Moments" })).toBeTruthy();
    expect(screen.getByText(/Planning stage/)).toBeTruthy();
    expect(await screen.findByText("Desktop host 0.0.0 (planning)")).toBeTruthy();
    expect(invoke).toHaveBeenCalledWith("app_info");
    expect(await screen.findByText("Worker: starting…")).toBeTruthy();
  });

  it("reports when the desktop host is unavailable", async () => {
    mockHost(Promise.reject(new Error("no host")), { status: "stopped" });
    render(<App />);

    expect(await screen.findByText(/Desktop host unavailable/)).toBeTruthy();
  });

  it("follows live worker status events", async () => {
    mockHost(Promise.resolve({ name: "OpenWorld Moments", version: "0.0.0", stage: "planning" }), {
      status: "starting",
    });
    render(<App />);
    await screen.findByText("Worker: starting…");
    await act(async () => {
      statusListener?.({ payload: { status: "ready", port: 1, pid: 2, restarts: 1 } });
    });
    expect(screen.getByText("Worker: ready (restarted 1×)")).toBeTruthy();
    await act(async () => {
      statusListener?.({
        payload: {
          status: "failed",
          code: "worker.crash_loop",
          message: "crashed",
          stderr_tail: "",
        },
      });
    });
    expect(screen.getByText("Worker unavailable: crashed")).toBeTruthy();
  });
});
