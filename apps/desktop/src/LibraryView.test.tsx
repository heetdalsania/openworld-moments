// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PAGE_SIZE } from "./api";
import { LibraryView } from "./LibraryView";
import { invalidate, resetQueries } from "./query";
import { asset, createHost, type FakeHost, install, must } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const FIRST = "GET /v1/assets?order=newest&limit=60";
let host: FakeHost;

function page(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => {
    const n = String(start + i).padStart(4, "0");
    return asset({ id: `ast_01JCBQ0000000000000000${n}`, original_name: `Clip ${start + i}.mp4` });
  });
}

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  resetQueries();
});

describe("library", () => {
  it("shows a loading state, then clips with their badges", async () => {
    host.route(FIRST, [
      asset({ missing_at: "2026-11-22T10:00:00Z" }),
      asset({
        id: "ast_01JCBQ00000000000000000002",
        original_name: "Night drive.mkv",
        audio: [],
        video: {
          codec: "hevc",
          width: 3840,
          height: 2160,
          frame_rate: { num: 60, den: 1 },
          color: { hdr: true, transfer: "smpte2084" },
        },
      }),
    ]);
    render(<LibraryView onImport={() => undefined} />);
    expect(screen.getByRole("status").textContent).toMatch(/Loading your library/);
    const grid = await screen.findByRole("list", { name: "2 clips" });
    const links = within(grid).getAllByRole("link");
    const first = must(links[0], "first card");
    const second = must(links[1], "second card");
    expect(within(first).getByText("Original missing")).toBeTruthy();
    expect(within(first).getByText("1:02 · 1920×1080")).toBeTruthy();
    expect(within(second).getByText("HDR")).toBeTruthy();
    expect(within(second).getByText("No audio")).toBeTruthy();
    expect(first.getAttribute("href")).toBe("#/asset/ast_01JCBQ00000000000000000001");
  });

  it("offers import from the empty state", async () => {
    host.route(FIRST, []);
    const onImport = vi.fn();
    const user = userEvent.setup();
    render(<LibraryView onImport={onImport} />);
    expect(await screen.findByRole("heading", { name: "No clips yet" })).toBeTruthy();
    expect(screen.getByText(/originals stay untouched/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Import media" }));
    expect(onImport).toHaveBeenCalledOnce();
  });

  it("explains a load error and retries", async () => {
    let fail = true;
    host.route(FIRST, () => {
      if (fail) throw { code: "worker.unavailable", message: "down", retryable: true };
      return [asset()];
    });
    const user = userEvent.setup();
    render(<LibraryView onImport={() => undefined} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/media worker is not running/);
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Heist finale.mp4")).toBeTruthy();
  });

  it("pages with a stable cursor and restarts after new imports", async () => {
    const one = page(1, PAGE_SIZE);
    host.route(FIRST, one);
    host.route(
      `GET /v1/assets?order=newest&limit=60&after=${must(one[PAGE_SIZE - 1]).id}`,
      page(100, 3),
    );
    const user = userEvent.setup();
    render(<LibraryView onImport={() => undefined} />);
    await screen.findByRole("list", { name: `${PAGE_SIZE} clips` });
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("list", { name: `${PAGE_SIZE + 3} clips` })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull(); // last page

    // A finished import refreshes the first page; paging starts over from the top.
    host.route(FIRST, [asset({ id: "ast_01JCBQ00000000000000000999", original_name: "New.mp4" })]);
    invalidate("assets");
    expect(await screen.findByRole("list", { name: "1 clips" })).toBeTruthy();
    expect(screen.getByText("New.mp4")).toBeTruthy();
  });

  it("falls back to a placeholder when a thumbnail is not ready", async () => {
    host.route(FIRST, [asset()]);
    const { container } = render(<LibraryView onImport={() => undefined} />);
    await screen.findByText("Heist finale.mp4");
    const img = must(container.querySelector("img.thumb"), "thumbnail");
    expect(img.getAttribute("src")).toBe(
      "owm-media://localhost/asset/ast_01JCBQ00000000000000000001/thumbnail/1",
    );
    img.dispatchEvent(new Event("error"));
    expect(await screen.findByText("Heist finale.mp4")).toBeTruthy();
    expect(container.querySelector(".thumb.placeholder")).toBeTruthy();
  });
});
