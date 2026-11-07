// SPDX-License-Identifier: AGPL-3.0-or-later
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Session } from "./api";
import { resetJobs, useJobs } from "./jobs";
import { resetQueries } from "./query";
import { SessionsView, uniqueDurationMs } from "./SessionsView";
import { createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const OLD = "ses_01JCBQ00000000000000000001";
const NEW = "ses_01JCBQ00000000000000000002";
let host: FakeHost;

function session(id: string, overrides: Partial<Session> = {}): Session {
  return {
    schema_version: "1.8",
    id,
    title: id === OLD ? "Friday night" : "Saturday evening",
    review_state: "unreviewed",
    grouping_confidence: 0.82,
    assets: [
      {
        asset_id: "ast_01JCBQ00000000000000000001",
        order_index: 0,
        session_start_ms: 0,
        duration_ms: 60_000,
      },
      {
        asset_id: "ast_01JCBQ00000000000000000002",
        order_index: 1,
        session_start_ms: 50_000,
        duration_ms: 60_000,
        overlap_with_previous_ms: 10_000,
        alignment_confidence: 0.9,
      },
    ],
    created_at: "2026-11-21T09:00:00Z",
    ...overrides,
  } as Session;
}

function JobCount() {
  const { jobs } = useJobs();
  return <output aria-label="jobs">{jobs.map((j) => j.kind).join(",")}</output>;
}

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  window.location.hash = "#/sessions";
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
});

describe("sessions list", () => {
  it("counts played time without the hidden repeated footage", () => {
    expect(uniqueDurationMs(session(OLD))).toBe(110_000);
  });

  it("lists sessions with their state, confidence, and hidden footage", async () => {
    host.route("GET /v1/sessions?limit=200", [
      session(NEW),
      session(OLD, { review_state: "corrected", grouping_confidence: null }),
    ]);
    render(<SessionsView />);
    const list = await screen.findByRole("list", { name: "2 sessions" });
    const first = within(list).getByRole("link", { name: /Saturday evening/ });
    expect(first.getAttribute("href")).toBe(`#/session/${NEW}`);
    expect(first.textContent).toContain("2 clips · 1:50 · 0:10 repeated footage hidden");
    expect(first.textContent).toContain("Grouping confidence 82%");
    const second = within(list).getByRole("link", { name: /Friday night/ });
    expect(second.textContent).toContain("Edited by you");
    expect(second.textContent).not.toContain("Grouping confidence");
  });

  it("shows an empty state and starts grouping and alignment jobs", async () => {
    host.route("GET /v1/sessions?limit=200", []);
    host.route("POST /v1/sessions/recompute", () => job({ kind: "group" }));
    host.route("POST /v1/sessions/align", () => job({ kind: "align" }));
    const user = userEvent.setup();
    render(
      <>
        <SessionsView />
        <JobCount />
      </>,
    );
    await screen.findByRole("heading", { name: "No sessions yet" });
    await user.click(screen.getByRole("button", { name: "Group clips into sessions" }));
    await user.click(screen.getByRole("button", { name: "Find repeated footage" }));
    expect(host.posts("/v1/sessions/recompute")).toEqual([{}]);
    expect(host.posts("/v1/sessions/align")).toEqual([{}]);
    expect(screen.getByRole("status", { name: "jobs" }).textContent).toContain("group");
  });

  it("merges selected sessions into the earliest and opens it", async () => {
    host.route("GET /v1/sessions?limit=200", [session(NEW), session(OLD)]);
    host.route("POST /v1/sessions/merge", () => session(OLD, { review_state: "corrected" }));
    const user = userEvent.setup();
    render(<SessionsView />);
    const merge = await screen.findByRole("button", { name: "Merge selected" });
    expect(merge).toHaveProperty("disabled", true);
    await user.click(screen.getByRole("checkbox", { name: "Select Saturday evening to merge" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Friday night to merge" }));
    await user.click(screen.getByRole("button", { name: "Merge selected (2)" }));
    expect(host.posts("/v1/sessions/merge")).toEqual([{ session_ids: [OLD, NEW] }]);
    expect(window.location.hash).toBe(`#/session/${OLD}`);
  });

  it("reports load and action errors", async () => {
    let fail = true;
    host.route("GET /v1/sessions?limit=200", () => {
      if (fail) throw { code: "storage.busy", message: "Worker is restarting.", retryable: true };
      return [session(NEW), session(OLD)];
    });
    host.route("POST /v1/sessions/merge", () => {
      throw { code: "session.in_use", message: "A session has stories.", retryable: false };
    });
    const user = userEvent.setup();
    render(<SessionsView />);
    expect((await screen.findByRole("alert")).textContent).toContain("Worker is restarting.");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("list", { name: "2 sessions" });
    for (const box of screen.getAllByRole("checkbox")) await user.click(box);
    await user.click(screen.getByRole("button", { name: "Merge selected (2)" }));
    expect((await screen.findByRole("alert")).textContent).toContain("A session has stories.");
    expect(window.location.hash).toBe("#/sessions");
  });
});
