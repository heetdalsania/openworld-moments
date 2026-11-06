// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImportPanel } from "./ImportPanel";
import { resetJobs, useJobs } from "./jobs";
import { createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
const open = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open }));

let host: FakeHost;

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  open.mockReset();
  resetJobs();
});

function JobCount() {
  return <span data-testid="jobs">{useJobs().jobs.length}</span>;
}

describe("import dialog", () => {
  it("collects files and folders, then imports them by reference", async () => {
    open
      .mockResolvedValueOnce(["/captures/a.mp4", "/captures/b.mov"])
      .mockResolvedValueOnce("/captures/Halo");
    host.route("POST /v1/imports", job({ kind: "import" }));
    const onClose = vi.fn();
    const onStarted = vi.fn();
    const user = userEvent.setup();
    render(
      <>
        <ImportPanel initialPaths={[]} onClose={onClose} onStarted={onStarted} />
        <JobCount />
      </>,
    );
    const start = screen.getByRole("button", { name: "Import" }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "Choose files…" }));
    await user.click(screen.getByRole("button", { name: "Choose folder…" }));
    expect(open).toHaveBeenCalledWith(
      expect.objectContaining({ directory: false, multiple: true }),
    );
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ directory: true }));
    const selected = screen.getByRole("list", { name: "Selected for import" });
    expect(within(selected).getAllByRole("listitem")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Remove b.mov from the selection" }));
    await user.click(screen.getByRole("button", { name: "Import 2" }));
    expect(host.posts("/v1/imports")).toEqual([
      { paths: ["/captures/a.mp4", "/captures/Halo"], mode: "reference", recursive: true },
    ]);
    expect(onStarted).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.getByTestId("jobs").textContent).toBe("1"); // visible in the job center at once
    expect(screen.getByText(/never moved, changed, or deleted/)).toBeTruthy();
  });

  it("remembers the managed choice", async () => {
    host.route("POST /v1/imports", job({ kind: "import" }));
    const user = userEvent.setup();
    render(
      <ImportPanel
        initialPaths={["/captures/a.mp4"]}
        onClose={() => undefined}
        onStarted={() => undefined}
      />,
    );
    await user.click(screen.getByRole("radio", { name: /Copy into the library/ }));
    await user.click(screen.getByRole("button", { name: "Import 1" }));
    expect(host.posts("/v1/imports")[0]).toMatchObject({ mode: "managed" });
    cleanup();
    render(<ImportPanel initialPaths={[]} onClose={() => undefined} onStarted={() => undefined} />);
    expect(
      (screen.getByRole("radio", { name: /Copy into the library/ }) as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("keeps the dialog open and explains a failure", async () => {
    host.route("POST /v1/imports", () => {
      throw {
        code: "job.invalid_params",
        message: "'paths[0]' must be an absolute path",
        retryable: false,
      };
    });
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <ImportPanel initialPaths={["relative.mp4"]} onClose={onClose} onStarted={() => undefined} />,
    );
    await user.click(screen.getByRole("button", { name: "Import 1" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/must be an absolute path/);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("ignores a cancelled picker", async () => {
    open.mockResolvedValue(null);
    const user = userEvent.setup();
    render(<ImportPanel initialPaths={[]} onClose={() => undefined} onStarted={() => undefined} />);
    await user.click(screen.getByRole("button", { name: "Choose files…" }));
    expect(screen.getByText(/Nothing selected yet/)).toBeTruthy();
  });
});
