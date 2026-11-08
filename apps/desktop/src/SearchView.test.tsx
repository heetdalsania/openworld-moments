// SPDX-License-Identifier: AGPL-3.0-or-later
// Search (M26) through the fake host: results with time ranges, safe snippets,
// facet filters, index maintenance, keyboard movement and collections.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchResult, SearchResults } from "./api";
import { describeRule } from "./CollectionsPanel";
import { resetJobs } from "./jobs";
import { resetQueries } from "./query";
import { resultHref } from "./SearchResult";
import { SearchView } from "./SearchView";
import { createHost, type FakeHost, install, job } from "./testing/fakeHost";

const invoke = vi.hoisted(() => vi.fn());
const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const SES = "ses_01JCBQ00000000000000000002";
const AST = "ast_01JCBQ00000000000000000001";
const EVT = "evt_01JCBQ00000000000000000003";
const COL = "col_01JCBQ00000000000000000061";
let host: FakeHost;
let indexStatus: Record<string, unknown>;

const eventResult: SearchResult = {
  key: `event:${EVT}`,
  kind: "event",
  title: [
    { text: "openworld.", match: false },
    { text: "wanted", match: true },
    { text: "_level_changed", match: false },
  ],
  snippet: [
    { text: "<img src=x onerror=alert(1)> ", match: false },
    { text: "WANTED", match: true },
  ],
  matched_in: ["label", "on-screen text"],
  session_id: SES,
  asset_id: AST,
  event_id: EVT,
  range: { timebase: "session", start_ms: 64_000, end_ms: 66_500 },
  confidence: 0.97,
  review_state: "confirmed",
  source_kind: "xbox",
  event_type: "openworld.wanted_level_changed",
};

function results(items: SearchResult[], total = items.length): SearchResults {
  return {
    schema_version: "1.20",
    query: { text: "wanted", terms: ["wanted"], ignored: [] },
    filters: {},
    offset: 0,
    limit: 25,
    total,
    items,
    facets: {
      kind: [{ value: "event", count: total }],
      event_type: [{ value: "openworld.wanted_level_changed", count: total }],
      review_state: [{ value: "confirmed", count: total }],
      source_kind: [{ value: "xbox", count: total }],
    },
    index_status: "current",
    took_ms: 4,
  };
}

beforeEach(() => {
  host = createHost();
  install(host, { invoke, listen });
  indexStatus = {
    schema_version: "1.20",
    index_version: 1,
    expected_version: 1,
    status: "current",
    reasons: [],
    documents: { clip: 2, session: 1, event: 3, transcript: 4, project: 0 },
    checked: false,
  };
  host.route("GET /v1/search/index", () => indexStatus);
  host.route("GET /v1/search/index?check=true", () => ({ ...indexStatus, checked: true }));
  host.route("GET /v1/jobs?limit=200", []);
  host.route("GET /v1/collections", [
    {
      id: COL,
      name: "Best of",
      kind: "manual",
      item_count: 0,
      created_at: "2026-11-21T12:00:00Z",
      updated_at: "2026-11-21T12:00:00Z",
    },
  ]);
  host.route("POST /v1/search", (body: unknown) =>
    (body as { query: string }).query ? results([eventResult]) : results([], 0),
  );
});

afterEach(() => {
  cleanup();
  invoke.mockReset();
  listen.mockReset();
  resetQueries();
  resetJobs();
});

describe("search view", () => {
  it("shows results with their exact moment, rendering text safely", async () => {
    const user = userEvent.setup();
    render(<SearchView workerReady />);
    await user.type(screen.getByRole("searchbox", { name: "Search your library" }), "wanted");
    const list = await screen.findByRole("list", { name: "Results" });
    const link = within(list).getByRole("link");
    expect(link.getAttribute("href")).toBe(`#/session/${SES}@64000`);
    expect(link.textContent).toContain("1:04–1:07");
    expect(link.textContent).toContain("97% confidence");
    expect(link.textContent).toContain("matched in label and on-screen text");
    // Matched words are marked; markup in recognized text stays text.
    expect([...link.querySelectorAll("mark")].map((m) => m.textContent)).toEqual([
      "wanted",
      "WANTED",
    ]);
    expect(link.querySelector("img")).toBeNull();
    expect(link.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(host.posts("/v1/search").at(-1)).toEqual({
      query: "wanted",
      filters: {},
      offset: 0,
      limit: 25,
    });
  });

  it("filters with facets, confidence, dates and durations", async () => {
    const user = userEvent.setup();
    render(<SearchView workerReady />);
    await user.type(screen.getByRole("searchbox"), "wanted");
    await user.click(await screen.findByRole("button", { name: "Event (1)" }));
    await user.click(screen.getByRole("button", { name: "confirmed (1)" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Minimum confidence" }), "0.8");
    await user.type(screen.getByLabelText("From"), "2026-11-01");
    await user.type(screen.getByLabelText("At least"), "2");
    await waitFor(() =>
      expect(host.posts("/v1/search").at(-1)).toEqual({
        query: "wanted",
        filters: {
          kinds: ["event"],
          review_states: ["confirmed"],
          min_confidence: 0.8,
          occurred_from: "2026-11-01T00:00:00Z",
          min_duration_ms: 2000,
        },
        offset: 0,
        limit: 25,
      }),
    );
    expect(screen.getByRole("button", { name: "Event (1)" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByRole("button", { name: "Event (1)" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("");
  });

  it("moves between the box and results with the arrow keys", async () => {
    const user = userEvent.setup();
    host.route("POST /v1/search", () =>
      results([
        eventResult,
        {
          ...eventResult,
          key: "event:evt_01JCBQ00000000000000000004",
          event_id: "evt_01JCBQ00000000000000000004",
        },
      ]),
    );
    render(<SearchView workerReady />);
    const box = screen.getByRole("searchbox");
    expect(document.activeElement).toBe(box);
    await user.type(box, "wanted");
    const links = within(await screen.findByRole("list", { name: "Results" })).getAllByRole("link");
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(links[0]);
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(document.activeElement).toBe(links[1]);
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(document.activeElement).toBe(box);
    await user.keyboard("{Escape}");
    expect((box as HTMLInputElement).value).toBe("");
  });

  it("explains refused queries and ignored characters", async () => {
    const user = userEvent.setup();
    host.route("POST /v1/search", (body: unknown) => {
      const query = (body as { query: string }).query;
      if (query === "w*") {
        throw {
          code: "search.prefix_too_short",
          message: "Type at least 2 letters before * to search by prefix.",
          retryable: false,
        };
      }
      return {
        ...results([], 0),
        query: { text: query, terms: [], ignored: query ? [query] : [] },
      };
    });
    render(<SearchView workerReady />);
    await user.type(screen.getByRole("searchbox"), "w*");
    expect((await screen.findByRole("alert")).textContent).toContain("2 letters before *");
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "!!!");
    expect(await screen.findByText(/ignored !!!/)).toBeTruthy();
    expect(screen.getByText(/Nothing matches/)).toBeTruthy();
  });

  it("rebuilds, checks and clears the derived index", async () => {
    const user = userEvent.setup();
    indexStatus = {
      ...indexStatus,
      status: "stale",
      reasons: ["documents_out_of_date"],
    };
    host.route("POST /v1/search/index/rebuild", () => job({ kind: "index", state: "ready" }));
    host.route("DELETE /v1/search/index", () => ({
      ...indexStatus,
      status: "cleared",
      reasons: ["cleared"],
    }));
    render(<SearchView workerReady />);
    expect((await screen.findByText(/may be incomplete/)).textContent).toContain(
      "some items are missing or out of date",
    );
    await user.click(screen.getByRole("button", { name: "Rebuild index" }));
    expect(host.posts("/v1/search/index/rebuild")).toEqual([{}]);
    await user.click(screen.getByRole("button", { name: "Check index" }));
    await waitFor(() =>
      expect(host.calls.some((c) => c.path === "/v1/search/index?check=true")).toBe(true),
    );
    await user.click(screen.getByRole("button", { name: "Clear index…" }));
    expect(host.calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Delete search index" }));
    await waitFor(() =>
      expect(host.calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual([
        "/v1/search/index",
      ]),
    );
  });

  it("adds results to a list and saves the search as a rule", async () => {
    const user = userEvent.setup();
    host.route(`POST /v1/collections/${COL}/items`, () => ({ item_id: 1, added: true }));
    host.route("POST /v1/collections", (body: unknown) => ({
      id: "col_01JCBQ00000000000000000062",
      name: (body as { name: string }).name,
      kind: "rule",
      rule: (body as { rule: unknown }).rule,
      created_at: "2026-11-21T12:00:00Z",
      updated_at: "2026-11-21T12:00:00Z",
    }));
    host.route("GET /v1/collections/col_01JCBQ00000000000000000062", {
      schema_version: "1.20",
      id: "col_01JCBQ00000000000000000062",
      name: "Wanted",
      kind: "rule",
      rule: { version: 1, query: "wanted", filters: { kinds: ["event"] } },
      created_at: "2026-11-21T12:00:00Z",
      updated_at: "2026-11-21T12:00:00Z",
      offset: 0,
      total: 1,
      items: [
        {
          ...eventResult,
          reasons: [
            { criterion: "text", detail: "Matches wanted in the label" },
            { criterion: "kind", detail: "Is an event (event allowed)" },
          ],
        },
      ],
    });
    render(<SearchView workerReady />);
    await user.type(screen.getByRole("searchbox"), "wanted");
    await user.selectOptions(
      await screen.findByRole("combobox", {
        name: /Add openworld.wanted_level_changed to a collection/,
      }),
      COL,
    );
    expect(await screen.findByText("Added to Best of")).toBeTruthy();
    expect(host.posts(`/v1/collections/${COL}/items`)).toEqual([{ kind: "event", id: EVT }]);
    await user.click(screen.getByRole("button", { name: "Event (1)" }));
    await user.type(screen.getByLabelText(/New collection name/), "Wanted");
    await user.click(screen.getByRole("button", { name: "Save search as rule" }));
    expect(host.posts("/v1/collections")).toEqual([
      { name: "Wanted", rule: { version: 1, query: "wanted", filters: { kinds: ["event"] } } },
    ]);
    const rule = await screen.findByRole("list", { name: "Rule" });
    expect(rule.textContent).toContain("Text matches wanted");
    expect(rule.textContent).toContain("Only events");
    const why = screen.getByRole("list", { name: /Why openworld.wanted_level_changed matched/ });
    expect(why.textContent).toContain("Is an event (event allowed)");
  });

  it("links every result kind to the right screen and time", () => {
    expect(
      resultHref({ ...eventResult, kind: "transcript", key: "transcript:3", transcript_id: 3 }),
    ).toBe(`#/session/${SES}@64000`);
    expect(
      resultHref({
        ...eventResult,
        kind: "clip",
        key: `clip:${AST}`,
        range: { timebase: "clip", start_ms: 0, end_ms: 9 },
      }),
    ).toBe(`#/asset/${AST}`);
    expect(resultHref({ ...eventResult, kind: "session", key: `session:${SES}` })).toBe(
      `#/session/${SES}`,
    );
    expect(
      resultHref({
        ...eventResult,
        kind: "project",
        key: "project:prj_01JCBQ00000000000000000005",
        project_id: "prj_01JCBQ00000000000000000005",
      }),
    ).toBe("#/project/prj_01JCBQ00000000000000000005");
    expect(
      describeRule({
        version: 1,
        query: "",
        filters: {
          min_confidence: 0.8,
          occurred_to: "2026-11-30T23:59:59Z",
          max_duration_ms: 5000,
        },
      }),
    ).toEqual(["Confidence at least 80%", "On or before 2026-11-30", "At most 5 s long"]);
  });
});
