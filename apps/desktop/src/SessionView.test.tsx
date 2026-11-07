// SPDX-License-Identifier: AGPL-3.0-or-later
// The session player and corrections (M13), end to end through the fake host: load a
// session, play across a boundary, seek with the keyboard, reveal repeated footage,
// and reorder clips.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssetDerivedMedia, AssetOverlap, Session } from "./api";
import { App } from "./App";
import { resetJobs } from "./jobs";
import { resetQueries } from "./query";
import { SessionView } from "./SessionView";
import { asset, createHost, type FakeHost, install, must } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: () => Promise.resolve(() => undefined),
  }),
}));

const SES = "ses_01JCBQ00000000000000000001";
const A = "ast_01JCBQ00000000000000000001";
const B = "ast_01JCBQ00000000000000000002";
const C = "ast_01JCBQ00000000000000000003";
const DURATIONS: Record<string, number> = { [A]: 2000, [B]: 2000, [C]: 1000 };
const NAMES: Record<string, string> = { [A]: "Part 1.mp4", [B]: "Part 2.mp4", [C]: "Part 3.mp4" };
const proxy = (id: string) => `owm-media://localhost/asset/${id}/proxy`;

let host: FakeHost;
let order: string[];
let overlapB: number;
let overlapSource: "auto" | "user";

/** The session as the worker would lay it out for the current order and overlap. */
function session(): Session {
  let start = 0;
  const assets = order.map((id, index) => {
    const overlap = index > 0 && id === B && order[index - 1] === A ? overlapB : 0;
    start = index === 0 ? 0 : start - overlap;
    const member = {
      asset_id: id,
      order_index: index,
      session_start_ms: start,
      duration_ms: DURATIONS[id] ?? 0,
      ...(index > 0 ? { overlap_with_previous_ms: overlap } : {}),
      ...(overlap > 0 && overlapSource === "auto" ? { alignment_confidence: 0.91 } : {}),
    };
    start += DURATIONS[id] ?? 0;
    return member;
  });
  return {
    schema_version: "1.8",
    id: SES,
    title: "Saturday evening",
    review_state: "unreviewed",
    grouping_confidence: 0.8,
    assets,
    created_at: "2026-11-21T09:00:00Z",
  } as Session;
}

function overlaps(): AssetOverlap[] {
  return [
    {
      schema_version: "1.8",
      asset_a: A,
      asset_b: B,
      algorithm: "owm-overlap",
      version: 1,
      status: "matched",
      current: true,
      offset_ms: 1400,
      overlap_ms: 600,
      confidence: 0.91,
      evidence: {},
      applied: { overlap_ms: overlapB, source: overlapSource, confidence: 0.91 },
    } as AssetOverlap,
  ];
}

function derived(id: string): AssetDerivedMedia {
  return {
    schema_version: "1.8",
    asset_id: id,
    proxy_decision: { needed: true, policy: "auto", policy_version: 1, reasons: [] },
    artifacts: [{ kind: "proxy", status: "ready" }],
  } as unknown as AssetDerivedMedia;
}

// jsdom has no media pipeline: give <video> a controllable clock.
const playing = new WeakSet<HTMLMediaElement>();
let failPlay = false;

beforeEach(() => {
  order = [A, B, C];
  overlapB = 600;
  overlapSource = "auto";
  failPlay = false;
  host = createHost();
  install(host, { invoke, listen });
  host.route(`GET /v1/sessions/${SES}`, () => session());
  host.route(`GET /v1/sessions/${SES}/overlaps`, () => overlaps());
  for (const id of [A, B, C]) {
    host.route(`GET /v1/assets/${id}`, () =>
      asset({
        id,
        original_name: NAMES[id],
        duration_ms: DURATIONS[id],
        video: {
          codec: "h264",
          width: 1920,
          height: 1080,
          frame_rate: { num: 50, den: 1 },
          color: { hdr: false },
        },
      }),
    );
    host.route(`GET /v1/assets/${id}/derived`, () => derived(id));
  }
  host.route("GET /v1/jobs?limit=200", []);
  host.route("GET /v1/sessions?limit=200", () => [session()]);
  host.route(`POST /v1/sessions/${SES}/order`, (body: unknown) => {
    order = (body as { asset_ids: string[] }).asset_ids;
    return session();
  });
  host.route(`PUT /v1/sessions/${SES}/overlaps/${B}`, (body: unknown) => {
    const value = (body as { overlap_ms: number | null }).overlap_ms;
    overlapB = value ?? 600;
    overlapSource = value === null ? "auto" : "user";
    return session();
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    if (failPlay) return Promise.reject(new Error("The clip could not be decoded."));
    playing.add(this);
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    playing.delete(this);
  });
  vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    return !playing.has(this);
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))),
  );
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function videos(): HTMLVideoElement[] {
  return [...document.querySelectorAll<HTMLVideoElement>("video.session-video")];
}

function activeVideo(): HTMLVideoElement {
  return must(document.querySelector<HTMLVideoElement>("video.session-video.active"), "video");
}

function clock(): string {
  return must(document.querySelector(".clock")?.textContent, "clock");
}

async function openSession() {
  render(<SessionView id={SES} />);
  await screen.findByRole("heading", { name: "Saturday evening" });
  await screen.findByText(/Clip 1 of 3: Part 1\.mp4 at 0:00\.00/);
}

describe("session view", () => {
  it("lays clips end to end with the repeated footage hidden and explained", async () => {
    await openSession();
    // 2000 + (2000 - 600) + 1000
    expect(clock()).toBe("0:00.00 / 0:04.40");
    const legend = screen.getByRole("list", { name: "Clip boundaries" });
    expect(within(legend).getByText("0:00.60 repeated footage hidden · 91% sure")).toBeTruthy();
    expect(within(legend).getByRole("button", { name: "0:02.00 · Part 2.mp4" })).toBeTruthy();
    expect(
      screen.getByText(/Starts with 0:00\.60 of footage .* \(found automatically, 91% sure\)/),
    ).toBeTruthy();
    const [first, second] = videos();
    expect(first?.getAttribute("src")).toBe(proxy(A));
    expect(second?.getAttribute("src")).toBe(proxy(B)); // preloaded at its first unique frame
    expect(second?.currentTime).toBeCloseTo(0.6);
    expect(second?.muted).toBe(true);
  });

  it("plays across a boundary without replaying the overlap", async () => {
    const user = userEvent.setup();
    await openSession();
    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    const first = activeVideo();
    first.currentTime = 1.995; // A's last frame
    fireEvent.timeUpdate(first);
    const second = activeVideo();
    expect(second).not.toBe(first);
    expect(second.getAttribute("src")).toBe(proxy(B));
    expect(second.currentTime).toBeCloseTo(0.6); // B starts after the repeated part
    expect(second.paused).toBe(false);
    expect(second.muted).toBe(false);
    expect(first.paused).toBe(true);
    expect(clock()).toBe("0:02.00 / 0:04.40");
    expect(screen.getByText(/Clip 2 of 3: Part 2\.mp4 at 0:00\.60/)).toBeTruthy();
    // The other element now waits at C.
    expect(first.getAttribute("src")).toBe(proxy(C));
  });

  it("controls the whole timeline from the keyboard", async () => {
    const user = userEvent.setup();
    await openSession();
    screen.getByRole("group", { name: "Session player" }).focus();
    await user.keyboard("{End}");
    expect(clock()).toBe("0:04.40 / 0:04.40");
    await user.keyboard("{Home}");
    expect(clock()).toBe("0:00.00 / 0:04.40");
    await user.keyboard("]");
    expect(clock()).toBe("0:02.00 / 0:04.40");
    expect(activeVideo().getAttribute("src")).toBe(proxy(B));
    await user.keyboard(",");
    expect(clock()).toBe("0:01.98 / 0:04.40"); // one 50 fps frame back, into A
    expect(activeVideo().getAttribute("src")).toBe(proxy(A));
    await user.keyboard(".");
    expect(clock()).toBe("0:02.00 / 0:04.40");
    await user.keyboard("{ArrowRight}");
    expect(clock()).toBe("0:04.40 / 0:04.40"); // clamped at the end
    await user.keyboard("{ArrowLeft}");
    expect(clock()).toBe("0:00.00 / 0:04.40");
    await user.keyboard("[[");
    expect(clock()).toBe("0:00.00 / 0:04.40");
    await user.keyboard(" ");
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    await user.keyboard("k");
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    await user.keyboard("m");
    expect(videos().every((v) => v.muted)).toBe(true);
  });

  it("reveals the hidden duplicate time and keeps the moment", async () => {
    const user = userEvent.setup();
    await openSession();
    screen.getByRole("group", { name: "Session player" }).focus();
    await user.keyboard("]"); // B at its 600 ms mark
    await user.keyboard("r");
    expect(screen.getByRole("checkbox", { name: /Show repeated footage/ })).toHaveProperty(
      "checked",
      true,
    );
    expect(clock()).toBe("0:02.60 / 0:05.00"); // A 2000 + B 600: nothing is hidden now
    expect(screen.getByText("First 0:00.60 repeats the previous clip")).toBeTruthy();
    // Seeking into the revealed range shows B's repeated start.
    fireEvent.change(screen.getByRole("slider", { name: "Position in session" }), {
      target: { value: "2100" },
    });
    expect(screen.getByText(/Clip 2 of 3: Part 2\.mp4 at 0:00\.10/)).toBeTruthy();
    await user.click(screen.getByRole("checkbox", { name: /Show repeated footage/ }));
    // Hidden again: B's 100 ms mark is repeated footage, shown at the same moment in A.
    expect(screen.getByText(/Clip 1 of 3: Part 1\.mp4 at 0:01\.50/)).toBeTruthy();
  });

  it("reorders clips through the API and replays the new order", async () => {
    const user = userEvent.setup();
    await openSession();
    screen.getByRole("group", { name: "Session player" }).focus();
    await user.keyboard("{End}"); // in C
    await user.click(screen.getByRole("button", { name: "Move Part 3.mp4 earlier" }));
    expect(host.posts(`/v1/sessions/${SES}/order`)).toEqual([{ asset_ids: [A, C, B] }]);
    // No overlap applies out of capture order: 2000 + 1000 + 2000. Still at the end of
    // C, which now sits second.
    await waitFor(() => expect(clock()).toBe("0:03.00 / 0:05.00"));
    expect(screen.queryByText(/repeated footage hidden/)).toBeNull();
    expect(screen.getByText(/Clip 2 of 3: Part 3\.mp4 at 0:01\.00/)).toBeTruthy();
    const legend = screen.getByRole("list", { name: "Clip boundaries" });
    expect(
      within(legend)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["0:00.00 · Part 1.mp4", "0:02.00 · Part 3.mp4", "0:03.00 · Part 2.mp4"]);
  });

  it("overrides and restores a repeated-footage match", async () => {
    const user = userEvent.setup();
    await openSession();
    await user.click(
      screen.getByRole("button", { name: "Part 2.mp4 does not repeat the previous clip" }),
    );
    expect(host.calls.filter((c) => c.method === "PUT")).toEqual([
      { method: "PUT", path: `/v1/sessions/${SES}/overlaps/${B}`, body: { overlap_ms: 0 } },
    ]);
    await screen.findByText("You marked this clip as not repeating the previous one.");
    expect(clock()).toBe("0:00.00 / 0:05.00");
    await user.click(
      screen.getByRole("button", { name: "Use the automatic match for Part 2.mp4" }),
    );
    await screen.findByText(/found automatically, 91% sure/);
    expect(clock()).toBe("0:00.00 / 0:04.40");
  });

  it("splits, removes, and confirms through the API", async () => {
    host.route(`POST /v1/sessions/${SES}/split`, () => [session()]);
    host.route(`POST /v1/sessions/${SES}/remove`, () => [session()]);
    host.route(`POST /v1/sessions/${SES}/confirm`, () => ({
      ...session(),
      review_state: "confirmed",
    }));
    const user = userEvent.setup();
    await openSession();
    await user.click(screen.getByRole("button", { name: "Start a new session after Part 1.mp4" }));
    await user.click(
      screen.getByRole("button", { name: "Part 3.mp4 is not part of this session" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm session" }));
    expect(host.posts(`/v1/sessions/${SES}/split`)).toEqual([{ after_asset_id: A }]);
    expect(host.posts(`/v1/sessions/${SES}/remove`)).toEqual([{ asset_id: C }]);
    expect(host.posts(`/v1/sessions/${SES}/confirm`)).toHaveLength(1);
    // No split after the last clip.
    expect(
      screen.queryByRole("button", { name: "Start a new session after Part 3.mp4" }),
    ).toBeNull();
  });

  it("shows correction errors from the worker", async () => {
    host.route(`POST /v1/sessions/${SES}/order`, () => {
      throw { code: "session.invalid_request", message: "List every clip.", retryable: false };
    });
    const user = userEvent.setup();
    await openSession();
    await user.click(screen.getByRole("button", { name: "Move Part 2.mp4 later" }));
    expect((await screen.findByRole("alert")).textContent).toContain("List every clip.");
    expect(clock()).toBe("0:00.00 / 0:04.40"); // nothing changed
  });

  it("stops with a message when a clip cannot be played", async () => {
    const user = userEvent.setup();
    await openSession();
    failPlay = true;
    await user.click(screen.getByRole("button", { name: "Play" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "The clip could not be decoded.",
    );
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    failPlay = false;
    fireEvent.error(activeVideo());
    expect((await screen.findByRole("alert")).textContent).toContain(
      "This clip could not be played.",
    );
  });

  it("explains a clip that has no playable media", async () => {
    host.route(`GET /v1/assets/${C}/derived`, () => ({
      ...derived(C),
      artifacts: [{ kind: "proxy", status: "failed" }],
    }));
    host.route(`GET /v1/assets/${C}`, () =>
      asset({
        id: C,
        original_name: NAMES[C],
        duration_ms: 1000,
        missing_at: "2026-11-21T10:00:00Z",
      }),
    );
    await openSession();
    expect(
      screen.getByText(/cannot be played \(original offline, no playback copy\)/),
    ).toBeTruthy();
  });

  it("reports a session that cannot be loaded and retries", async () => {
    let fail = true;
    host.route(`GET /v1/sessions/${SES}`, () => {
      if (fail) throw { code: "session.not_found", message: "No such session.", retryable: false };
      return session();
    });
    const user = userEvent.setup();
    render(<SessionView id={SES} />);
    expect((await screen.findByRole("alert")).textContent).toContain("No such session.");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("heading", { name: "Saturday evening" });
  });
});

describe("sessions in the app", () => {
  it("opens a session from the list and plays it (E2E seek/play/reorder)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("link", { name: "Sessions" }));
    await user.click(await screen.findByRole("link", { name: /Saturday evening/ }));
    await screen.findByText(/Clip 1 of 3: Part 1\.mp4/);
    expect(screen.getByRole("link", { name: "Sessions" }).getAttribute("aria-current")).toBe(
      "page",
    );
    // Seek with the slider into B, play, cross into C.
    fireEvent.change(screen.getByRole("slider", { name: "Position in session" }), {
      target: { value: "3000" },
    });
    expect(screen.getByText(/Clip 2 of 3: Part 2\.mp4 at 0:01\.60/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Play" }));
    const b = activeVideo();
    await act(async () => {
      b.currentTime = 2.0;
      fireEvent.ended(b);
    });
    expect(activeVideo().getAttribute("src")).toBe(proxy(C));
    expect(clock()).toBe("0:03.40 / 0:04.40");
    // Reorder while playing: the clip and moment are kept.
    await user.click(screen.getByRole("button", { name: "Move Part 3.mp4 earlier" }));
    await waitFor(() => expect(clock()).toBe("0:02.00 / 0:05.00"));
    expect(screen.getByText(/Clip 2 of 3: Part 3\.mp4 at 0:00\.00/)).toBeTruthy();
  });
});
