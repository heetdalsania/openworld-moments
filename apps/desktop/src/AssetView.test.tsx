// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssetDerivedMedia } from "./api";
import { AssetView } from "./AssetView";
import { reloadJobs, resetJobs, upsertJob } from "./jobs";
import { resetQueries } from "./query";
import { ASSET_ID, asset, createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
const open = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/plugin-dialog", () => ({ open }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const KEY = "ab".repeat(32);
let host: FakeHost;

type Artifact = AssetDerivedMedia["artifacts"][number];

function ready(kind: "proxy" | "filmstrip" | "waveform"): Artifact {
  const base = {
    kind,
    status: "ready",
    cache_key: KEY,
    size_bytes: 10,
    sha256: KEY,
    created_at: "2026-11-21T09:05:00Z",
    recipe: { preset: { id: "p", version: 1 }, tool: { ffmpeg: "7.1", libraries: {} } },
  };
  if (kind === "proxy") {
    return {
      ...base,
      path: `derived/${ASSET_ID}/proxy-${KEY.slice(0, 16)}.mp4`,
      proxy: {
        width: 1280,
        height: 720,
        video_codec: "h264",
        pixel_format: "yuv420p",
        audio: true,
        duration_ms: 61_500,
        frame_rate: "source",
        tone_mapped: false,
      },
    } as Artifact;
  }
  if (kind === "filmstrip") {
    return {
      ...base,
      path: `derived/${ASSET_ID}/filmstrip-${KEY.slice(0, 16)}`,
      filmstrip: {
        count: 2,
        width: 160,
        height: 90,
        format: "jpeg",
        times_ms: [15_000, 45_000],
        source: "proxy",
      },
    } as Artifact;
  }
  return {
    ...base,
    path: `derived/${ASSET_ID}/waveform-${KEY.slice(0, 16)}.bin`,
    waveform: {
      format: "owm-waveform",
      format_version: 1,
      buckets_per_second: 50,
      sample_rate_hz: 8000,
      bucket_count: 3075,
    },
  } as Artifact;
}

function derived(artifacts: AssetDerivedMedia["artifacts"], needed = true): AssetDerivedMedia {
  return {
    schema_version: "1.6",
    asset_id: ASSET_ID,
    proxy_decision: {
      needed,
      policy: "auto",
      policy_version: 1,
      reasons: needed ? [{ code: "codec", detail: "Video codec 'hevc' is not H.264." }] : [],
    },
    artifacts,
  };
}

const failed = (kind: "proxy" | "filmstrip" | "waveform", code = "derived.disk_full"): Artifact =>
  ({
    kind,
    status: "failed",
    cache_key: KEY,
    last_error: { code, message: "Not enough space.", retryable: true },
  }) as Artifact;

beforeEach(async () => {
  host = createHost();
  install(host, { invoke, listen });
  host.route(`GET /v1/assets/${ASSET_ID}`, asset());
  host.route("GET /v1/jobs?limit=200", []);
  host.route(`POST /v1/assets/${ASSET_ID}/derived`, () =>
    job({ kind: "proxy", state: "queued", params: { asset_id: ASSET_ID } }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))),
  );
  await reloadJobs();
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  open.mockReset();
  resetQueries();
  resetJobs();
  vi.unstubAllGlobals();
});

function video(): HTMLVideoElement | null {
  return document.querySelector("video");
}

describe("asset view", () => {
  it("plays the proxy, and can switch to the original", async () => {
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([ready("proxy"), ready("filmstrip"), ready("waveform")]),
    );
    const user = userEvent.setup();
    render(<AssetView id={ASSET_ID} />);
    await screen.findByRole("heading", { name: "Heist finale.mp4" });
    await screen.findByText("Playback copy", { selector: "li span" });
    expect(video()?.getAttribute("src")).toBe(`owm-media://localhost/asset/${ASSET_ID}/proxy`);
    await user.click(screen.getByRole("radio", { name: "Original file" }));
    expect(video()?.getAttribute("src")).toBe(`owm-media://localhost/asset/${ASSET_ID}/original`);
    // Thumbnails seek the player.
    await user.click(screen.getByRole("button", { name: "Jump to 0:45" }));
    expect(video()?.currentTime).toBe(45);
    expect(host.posts(`/v1/assets/${ASSET_ID}/derived`)).toEqual([]); // nothing to prepare
    expect(screen.getByText(/never changes, moves, or deletes your original/)).toBeTruthy();
  });

  it("plays the original directly when no proxy is needed", async () => {
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived(
        [
          { kind: "proxy", status: "not_needed" } as Artifact,
          ready("filmstrip"),
          ready("waveform"),
        ],
        false,
      ),
    );
    render(<AssetView id={ASSET_ID} />);
    expect(await screen.findByText("Not needed: the original plays directly")).toBeTruthy();
    expect(video()?.getAttribute("src")).toBe(`owm-media://localhost/asset/${ASSET_ID}/original`);
    expect(
      (screen.getByRole("radio", { name: "Playback copy" }) as HTMLInputElement).disabled,
    ).toBe(true);
  });

  it("prepares playback automatically, once, and shows progress", async () => {
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([
        { kind: "proxy", status: "not_generated" } as Artifact,
        { kind: "filmstrip", status: "not_generated" } as Artifact,
        { kind: "waveform", status: "not_generated" } as Artifact,
      ]),
    );
    render(<AssetView id={ASSET_ID} />);
    await screen.findByText("Heist finale.mp4");
    await vi.waitFor(() => expect(host.posts(`/v1/assets/${ASSET_ID}/derived`)).toHaveLength(1));
    // The original is offered with a warning while the copy is prepared.
    expect(await screen.findByText(/may not play smoothly here/)).toBeTruthy();
    act(() =>
      upsertJob(
        job({
          id: "job_01JCBQ00000000000000000077",
          kind: "proxy",
          state: "proxying",
          params: { asset_id: ASSET_ID },
          progress: { done: 400, total: 1000 },
          message: "Creating proxy",
        }),
      ),
    );
    expect(await screen.findByText("Creating proxy")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Rebuild playback media" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(host.posts(`/v1/assets/${ASSET_ID}/derived`)).toHaveLength(1);
  });

  it("distinguishes a missing original from a failed playback copy", async () => {
    // Missing original, proxy fine: notice, original disabled, proxy plays.
    host.route(`GET /v1/assets/${ASSET_ID}`, asset({ missing_at: "2026-11-22T10:00:00Z" }));
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([ready("proxy"), ready("filmstrip"), ready("waveform")]),
    );
    const first = render(<AssetView id={ASSET_ID} />);
    expect(await screen.findByText(/original file is missing or offline/)).toBeTruthy();
    expect(screen.getByText(/Nothing was deleted/)).toBeTruthy();
    expect(
      (screen.getByRole("radio", { name: "Original file" }) as HTMLInputElement).disabled,
    ).toBe(true);
    expect(video()?.getAttribute("src")).toContain("/proxy");
    expect(screen.queryByText(/playback copy could not be made/)).toBeNull();
    first.unmount();
    resetQueries();

    // Original present, proxy failed: the failure and its reason, no missing notice.
    host.route(`GET /v1/assets/${ASSET_ID}`, asset());
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([failed("proxy"), ready("filmstrip"), ready("waveform")]),
    );
    render(<AssetView id={ASSET_ID} />);
    expect(
      await screen.findByText(/playback copy could not be made: There is not enough free space/),
    ).toBeTruthy();
    expect(screen.queryByText(/original file is missing/)).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(video()?.getAttribute("src")).toContain("/original");
  });

  it("retries a failed copy without forcing, and rebuilds with force", async () => {
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([failed("proxy"), ready("filmstrip"), ready("waveform")]),
    );
    const user = userEvent.setup();
    render(<AssetView id={ASSET_ID} />);
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(host.posts(`/v1/assets/${ASSET_ID}/derived`)).toEqual([{}]);
    cleanup();
    resetQueries();
    resetJobs();
    await reloadJobs();
    host.calls.length = 0;
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([ready("proxy"), ready("filmstrip"), ready("waveform")]),
    );
    render(<AssetView id={ASSET_ID} />);
    await user.click(await screen.findByRole("button", { name: "Rebuild playback media" }));
    expect(host.posts(`/v1/assets/${ASSET_ID}/derived`)).toEqual([{ force: true }]);
  });

  it("reports an unplayable original and an unknown clip", async () => {
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived(
        [
          { kind: "proxy", status: "not_needed" } as Artifact,
          ready("filmstrip"),
          ready("waveform"),
        ],
        false,
      ),
    );
    const view = render(<AssetView id={ASSET_ID} />);
    await screen.findByText("Not needed: the original plays directly");
    act(() => {
      video()?.dispatchEvent(new Event("error"));
    });
    expect(await screen.findByText(/cannot be played here/)).toBeTruthy();
    view.unmount();
    resetQueries();
    host.route(`GET /v1/assets/${ASSET_ID}`, () => {
      throw { code: "asset.not_found", message: "asset not found", retryable: false };
    });
    render(<AssetView id={ASSET_ID} />);
    expect(await screen.findByRole("heading", { name: "Clip not available" })).toBeTruthy();
  });

  it("never offers to delete or modify the original", async () => {
    host.route(
      `GET /v1/assets/${ASSET_ID}/derived`,
      derived([ready("proxy"), ready("filmstrip"), ready("waveform")]),
    );
    render(<AssetView id={ASSET_ID} />);
    await screen.findByText("Heist finale.mp4");
    const labels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(labels.some((l) => /delete|remove|trash|move|rename|overwrite/i.test(l))).toBe(false);
  });
});

it("locates a missing original through native selection and keeps cancellation inert", async () => {
  host.route(`GET /v1/assets/${ASSET_ID}`, asset({ missing_at: "2026-11-13T19:00:00Z" }));
  host.route(
    `GET /v1/assets/${ASSET_ID}/derived`,
    derived([failed("proxy"), failed("filmstrip"), failed("waveform")]),
  );
  host.route(`POST /v1/assets/${ASSET_ID}/relink`, job());
  const user = userEvent.setup();
  render(<AssetView id={ASSET_ID} />);
  const button = await screen.findByRole("button", { name: "Locate original or restore access…" });
  open.mockResolvedValueOnce(null);
  await user.click(button);
  expect(host.posts(`/v1/assets/${ASSET_ID}/relink`)).toEqual([]);
  open.mockResolvedValueOnce("/Volumes/Captures ✓/Original.mp4");
  await user.click(button);
  expect(open).toHaveBeenLastCalledWith({
    directory: false,
    multiple: false,
    title: "Locate this clip or restore access",
  });
  expect(host.posts(`/v1/assets/${ASSET_ID}/relink`)).toEqual([
    { path: "/Volumes/Captures ✓/Original.mp4" },
  ]);
});
