// SPDX-License-Identifier: AGPL-3.0-or-later
import type { EventDecision } from "@openworld-moments/contracts";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventReviewPanel, playbackToReview, reviewToPlayback } from "./EventReviewPanel";
import type { EventReview, EventReviewChange, EventReviewItem } from "./api";
import { resetJobs, upsertJob } from "./jobs";
import { invalidate, resetQueries } from "./query";
import { buildTimeline } from "./timeline";
import { createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));
const SID = "ses_01JCBQ00000000000000000001";
const EID = "evt_01JCBQ00000000000000000001";
const AID = "ast_01JCBQ00000000000000000001";
const key = "a".repeat(64);
const timeline = buildTimeline([{ assetId: AID, durationMs: 5000, overlapMs: 0 }]);
const source = {
  kind: "detector" as const,
  detector_id: "region-banner-ocr",
  detector_version: "1.0.0",
  profile_id: "generic-text",
  profile_version: "1.0.0",
  tool_versions: { ocr_engine: "tesseract-5.5.4" },
};
let host: FakeHost;
let entry: EventReviewItem;
const copy = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
function page(): EventReview {
  return {
    schema_version: "1.14",
    session_id: SID,
    layout_key: key,
    duration_ms: 5000,
    offset: 0,
    total: 1,
    items: [copy(entry)],
  };
}
beforeEach(() => {
  vi.stubGlobal("crypto", {
    subtle: { digest: vi.fn(async () => new Uint8Array(32).fill(170).buffer) },
  });
  resetQueries();
  resetJobs();
  host = createHost();
  install(host, { invoke, listen });
  const original = {
    schema_version: "1.14",
    id: EID,
    session_id: SID,
    asset_id: AID,
    type: "openworld.mission_completed",
    start_ms: 1000,
    end_ms: 3000,
    confidence: 0.95,
    attributes: { spoiler_risk: true },
    evidence: [
      {
        kind: "ocr" as const,
        text: "TASK COMPLETE",
        region: [0.1, 0.2, 0.8, 0.24] as [number, number, number, number],
        score: 0.95,
        frame_ms: 1000,
      },
    ],
    source,
    review_state: "unreviewed" as const,
  };
  entry = {
    original,
    effective: copy(original),
    revision: 0,
    status: "current",
    history: [],
    history_truncated: false,
  };
  host.route("GET /v1/profiles", [
    { id: "generic-text", display_name: "Synthetic text", profile_version: "1.0.0" },
  ]);
  host.route(`GET /v1/sessions/${SID}/review*`, () => page());
  host.route(`POST /v1/sessions/${SID}/review/${EID}`, (raw: unknown) => {
    const change = raw as EventReviewChange;
    if (change.expected_revision !== entry.revision)
      throw {
        code: "review.conflict",
        message: "Another review changed this event. Refresh and try again.",
      };
    entry.revision++;
    const state = {
      approve: "confirmed",
      reject: "rejected",
      reset: "unreviewed",
      correct: "corrected",
    } as const;
    if (change.action === "reset") entry.effective = copy(entry.original);
    else
      entry.effective = {
        ...entry.effective,
        review_state: state[change.action],
        ...(change.action === "correct"
          ? { type: change.type ?? "", start_ms: change.start_ms ?? 0, end_ms: change.end_ms ?? 0 }
          : {}),
      };
    (entry.history as EventDecision[]).push({
      revision: entry.revision,
      state: entry.effective.review_state,
      type: entry.effective.type,
      start_ms: entry.effective.start_ms,
      end_ms: entry.effective.end_ms,
      created_at: "2026-11-07T22:00:00Z",
    });
    return copy(entry);
  });
  host.route(`POST /v1/sessions/${SID}/review`, () => copy(entry));
  host.route(`POST /v1/sessions/${SID}/analyze`, () =>
    job({ kind: "analyze", state: "queued", params: { session_id: SID } }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetQueries();
  resetJobs();
  invoke.mockReset();
  listen.mockReset();
});
function panel() {
  const seek = vi.fn();
  render(<EventReviewPanel sessionId={SID} timeline={timeline} virtualMs={1500} onSeek={seek} />);
  return seek;
}

describe("event review", () => {
  it("inspects and seeks, approves, corrects, rejects and resets without changing the observation", async () => {
    const user = userEvent.setup();
    const original = copy(entry.original);
    const seek = panel();
    await screen.findByText("openworld.mission_completed");
    expect(screen.getByText(/Game compatibility is unvalidated/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Analyze events" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: /Review marker/ }));
    expect(seek).toHaveBeenLastCalledWith(1000);
    expect(screen.getByText(/Mission text may reveal spoilers/)).toBeTruthy();
    expect(screen.getByText(/tesseract-5.5.4/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Approve event" }));
    await waitFor(() => expect(entry.revision).toBe(1));
    await user.clear(screen.getByLabelText("Event type"));
    await user.type(screen.getByLabelText("Event type"), "openworld.corrected");
    await user.clear(screen.getByLabelText("Start seconds"));
    await user.type(screen.getByLabelText("Start seconds"), "1.25");
    await user.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(entry.effective.type).toBe("openworld.corrected"));
    expect(entry.effective.start_ms).toBe(1250);
    await user.click(screen.getByRole("button", { name: "Reject event" }));
    await waitFor(() => expect(entry.effective.review_state).toBe("rejected"));
    await user.click(screen.getByRole("button", { name: "Reset review" }));
    await waitFor(() => expect(entry.revision).toBe(4));
    expect(entry.original).toEqual(original);
    expect(entry.effective).toEqual(original);
  });
  it("creates an explicitly requested manual interval at the playhead", async () => {
    const user = userEvent.setup();
    panel();
    await screen.findByText("openworld.mission_completed");
    await user.click(screen.getByRole("button", { name: "Add event at playhead" }));
    expect((screen.getByLabelText("Start seconds") as HTMLInputElement).value).toBe("1.5");
    await user.click(screen.getByRole("button", { name: "Save manual event" }));
    await waitFor(() => expect(host.posts(`/v1/sessions/${SID}/review`)).toHaveLength(1));
    expect(host.posts(`/v1/sessions/${SID}/review`)[0]).toEqual({
      layout_key: key,
      type: "openworld.manual",
      start_ms: 1500,
      end_ms: 2500,
    });
  });
  it("retains historical corrections and prevents obsolete approvals", async () => {
    entry.status = "superseded";
    entry.effective.review_state = "corrected";
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "openworld.mission_completed" }));
    expect(screen.getByText(/Your decisions remain here/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Approve event" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
  it("keeps the edit revision captured when the user opened the form", async () => {
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole("button", { name: "openworld.mission_completed" }));
    entry.revision = 1;
    await act(async () => invalidate(`sessions:${SID}:review`));
    await screen.findByText(/revision 1/);
    await user.click(screen.getByRole("button", { name: "Save correction" }));
    await screen.findByRole("alert");
    expect(host.posts(`/v1/sessions/${SID}/review/${EID}`)[0]).toMatchObject({
      expected_revision: 0,
    });
  });
  it("disables cached markers and edits when the displayed layout differs", async () => {
    host.route(`GET /v1/sessions/${SID}/review*`, () => ({
      ...page(),
      layout_key: "b".repeat(64),
    }));
    const user = userEvent.setup();
    const seek = panel();
    await screen.findByText(/Verifying event timing/);
    expect(screen.queryByRole("button", { name: /Review marker/ })).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: /Seek openworld.mission_completed/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "openworld.mission_completed" }));
    expect(
      (screen.getByRole("button", { name: "Approve event" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Add event at playhead" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(seek).not.toHaveBeenCalled();
    expect(crypto.subtle.digest).toHaveBeenCalledWith(
      "SHA-256",
      new TextEncoder().encode(JSON.stringify([[AID, 5000, 0]])),
    );
  });
  it("fails closed when layout hashing is unavailable", async () => {
    vi.stubGlobal("crypto", {});
    panel();
    await screen.findByText(/Verifying event timing/);
    expect(
      (screen.getByRole("button", { name: "Add event at playhead" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
  it("starts only the chosen profile and exposes cancelled analysis", async () => {
    const user = userEvent.setup();
    panel();
    await screen.findByText("openworld.mission_completed");
    await user.selectOptions(screen.getByLabelText("Detector profile"), "generic-text");
    await user.click(screen.getByRole("button", { name: "Analyze events" }));
    expect(host.posts(`/v1/sessions/${SID}/analyze`)[0]).toEqual({
      profile_id: "generic-text",
      force: true,
    });
    await act(async () =>
      upsertJob(job({ kind: "analyze", state: "cancelled", params: { session_id: SID } })),
    );
    await screen.findByText(/Event analysis cancelled/);
  });
  it("shows empty, loading and failure states with a refresh action", async () => {
    host.route(`GET /v1/sessions/${SID}/review*`, () => ({ ...page(), items: [], total: 0 }));
    panel();
    await screen.findByText(/No events yet/);
    host.route(`GET /v1/sessions/${SID}/review*`, () => {
      throw { message: "Worker temporarily unavailable" };
    });
    await userEvent.click(screen.getByRole("button", { name: "Refresh events" }));
    await screen.findByRole("alert");
  });
});
it("maps unique review times into revealed playback without replaying the wrong clip", () => {
  const members = [
    { assetId: AID, durationMs: 5000, overlapMs: 0 },
    { assetId: "other", durationMs: 5000, overlapMs: 2000 },
  ];
  const revealed = buildTimeline(members, { reveal: true });
  expect(reviewToPlayback(revealed, 5500)).toBe(7500);
  expect(playbackToReview(revealed, 7500)).toBe(5500);
  // A hidden repeated moment resolves to its identical earlier clip.
  expect(playbackToReview(revealed, 5500)).toBe(3500);
});
