// SPDX-License-Identifier: AGPL-3.0-or-later
// Search (M26): local full-text search with facets, timestamp results that open
// at the matching moment, index maintenance and collections. Keyboard-complete:
// "/" or Ctrl/Cmd+K focuses the box, arrow keys move through results, Enter opens.
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  addToCollection,
  clearSearchIndex,
  type CollectionSummary,
  describeError,
  listCollections,
  rebuildSearchIndex,
  search,
  type SearchFilters,
  type SearchIndexStatus,
  searchIndexStatus,
  type SearchResult,
  type SearchResults,
} from "./api";
import { CollectionsPanel } from "./CollectionsPanel";
import { isActive, upsertJob, useJobs } from "./jobs";
import { invalidate, useAction, useQuery } from "./query";
import { KIND_LABELS, resultHref, ResultBody, resultTitle } from "./SearchResult";

const PAGE = 25;
const FACET_GROUPS = [
  { facet: "kind", filter: "kinds", label: "Kind" },
  { facet: "event_type", filter: "event_types", label: "Event label" },
  { facet: "review_state", filter: "review_states", label: "Review state" },
  { facet: "source_kind", filter: "source_kinds", label: "Source" },
] as const;
type ListFilter = (typeof FACET_GROUPS)[number]["filter"];
const REASONS: Record<string, string> = {
  version_changed: "the index format changed in this version",
  rebuild_incomplete: "a rebuild did not finish",
  cleared: "the index was cleared",
  documents_out_of_date: "some items are missing or out of date",
  full_text_corrupt: "the full-text index is damaged",
};

function AddToCollection({
  result,
  collections,
}: {
  result: SearchResult;
  collections: CollectionSummary[];
}) {
  const [done, setDone] = useState<string | null>(null);
  const add = useAction(async (id: string) => {
    const ident = result.kind === "transcript" ? result.transcript_id : idFor(result);
    if (ident === undefined) return;
    const outcome = await addToCollection(id, { kind: result.kind, id: ident });
    const name = collections.find((c) => c.id === id)?.name ?? "the collection";
    setDone(outcome.added ? `Added to ${name}` : `Already in ${name}`);
    invalidate(`collection:${id}`, "collection:list");
  });
  const manual = collections.filter((c) => c.kind === "manual");
  if (manual.length === 0) return null;
  return (
    <span className="add-to-collection">
      <select
        aria-label={`Add ${resultTitle(result)} to a collection`}
        value=""
        disabled={add.busy}
        onChange={(e) => {
          if (e.target.value) void add.run(e.target.value);
        }}
      >
        <option value="">Add to collection…</option>
        {manual.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {done && <span role="status">{done}</span>}
      {add.error && <span role="alert">{describeError(add.error)}</span>}
    </span>
  );
}

function idFor(result: SearchResult): string | undefined {
  switch (result.kind) {
    case "clip":
      return result.asset_id;
    case "session":
      return result.session_id;
    case "event":
      return result.event_id;
    case "project":
      return result.project_id;
    default:
      return undefined;
  }
}

function IndexStatus({ workerReady }: { workerReady: boolean }) {
  const [check, setCheck] = useState(false);
  const status = useQuery<SearchIndexStatus>(
    workerReady ? `search:index:${check ? "check" : "light"}` : null,
    () => searchIndexStatus(check),
  );
  const { jobs } = useJobs();
  const running = jobs.find((j) => j.kind === "index" && isActive(j));
  const rebuild = useAction(async () => upsertJob(await rebuildSearchIndex()));
  const clear = useAction(async () => {
    await clearSearchIndex();
    invalidate("search");
  });
  const [confirmClear, setConfirmClear] = useState(false);
  const failure = rebuild.error ?? clear.error;
  const data = status.data;
  const healthy = data?.status === "current";
  return (
    <div className={healthy ? "index-status" : "index-status notice-box"}>
      {status.error && <p role="alert">Index status unavailable: {describeError(status.error)}</p>}
      {data && (
        <p role="status">
          {running
            ? `Rebuilding the search index${running.progress ? ` (${Math.round((running.progress.done / running.progress.total) * 100)}%)` : ""}…`
            : healthy
              ? `Search index is up to date (${Object.values(data.documents).reduce((a, b) => a + b, 0)} items${data.checked ? ", fully checked" : ""}).`
              : `Search results may be incomplete: ${data.reasons.map((r) => REASONS[r] ?? r).join("; ")}.`}
        </p>
      )}
      <div className="row">
        <button
          type="button"
          className={healthy ? undefined : "primary"}
          disabled={!workerReady || Boolean(running) || rebuild.busy}
          onClick={() => void rebuild.run()}
        >
          Rebuild index
        </button>
        <button
          type="button"
          disabled={!workerReady || status.loading}
          onClick={() => (check ? status.refetch() : setCheck(true))}
        >
          Check index
        </button>
        {confirmClear ? (
          <>
            <span>Delete all derived search text? Clips, events and transcripts stay.</span>
            <button
              type="button"
              className="danger"
              disabled={clear.busy}
              onClick={() => {
                setConfirmClear(false);
                void clear.run();
              }}
            >
              Delete search index
            </button>
            <button type="button" onClick={() => setConfirmClear(false)}>
              Keep it
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={!workerReady || Boolean(running)}
            onClick={() => setConfirmClear(true)}
          >
            Clear index…
          </button>
        )}
      </div>
      {failure && <p role="alert">{describeError(failure)}</p>}
    </div>
  );
}

/** A copy of the filters with one field set, or removed when the value is undefined. */
function withField(
  filters: SearchFilters,
  key: keyof SearchFilters,
  value: unknown,
): SearchFilters {
  const kept = Object.entries(filters).filter(([k]) => k !== key);
  return Object.fromEntries(value === undefined ? kept : [...kept, [key, value]]) as SearchFilters;
}

function dateBound(value: string, end: boolean): string | undefined {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? `${value}T${end ? "23:59:59" : "00:00:00"}Z`
    : undefined;
}

export function SearchView({ workerReady }: { workerReady: boolean }) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [offset, setOffset] = useState(0);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLOListElement>(null);

  // Search as you type, after a short pause.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(text.trim());
      setOffset(0);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [text]);

  const effective = useMemo<SearchFilters>(() => {
    const lower = dateBound(from, false);
    const upper = dateBound(to, true);
    const dated = withField(filters, "occurred_from", lower);
    return withField(dated, "occurred_to", upper && (!lower || upper >= lower) ? upper : undefined);
  }, [filters, from, to]);
  const request = { query, filters: effective, offset, limit: PAGE };
  const results = useQuery<SearchResults>(
    workerReady ? `search:results:${JSON.stringify(request)}` : null,
    () => search(request),
  );
  const collections = useQuery(workerReady ? "collection:list" : null, listCollections);
  const data = results.data;

  const toggle = (filter: ListFilter, value: string) => {
    setOffset(0);
    setFilters((current) => {
      const values = (current[filter] as string[] | undefined) ?? [];
      const next = values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
      return withField(current, filter, next.length ? next : undefined);
    });
  };
  const setNumber = (key: keyof SearchFilters, value: number | undefined) => {
    setOffset(0);
    setFilters((current) => {
      return withField(
        current,
        key,
        value === undefined || Number.isNaN(value) ? undefined : value,
      );
    });
  };
  const anyFilter = Object.keys(effective).length > 0;

  const links = () =>
    Array.from(list.current?.querySelectorAll<HTMLAnchorElement>("a.result") ?? []);
  const onInputKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      links()[0]?.focus();
    } else if (event.key === "Escape" && text) {
      event.preventDefault();
      setText("");
    } else if (event.key === "Enter") {
      event.preventDefault();
      setQuery(text.trim());
      setOffset(0);
    }
  };
  const onResultKey = (event: KeyboardEvent<HTMLAnchorElement>) => {
    const all = links();
    const index = all.indexOf(event.currentTarget);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      all[Math.min(index + 1, all.length - 1)]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (index <= 0) input.current?.focus();
      else all[index - 1]?.focus();
    }
  };

  return (
    <section className="view search-view" aria-labelledby="search-heading">
      <h1 id="search-heading">Search</h1>
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(text.trim());
        }}
      >
        <label htmlFor="search-input">Search your library</label>
        <input
          id="search-input"
          ref={input}
          type="search"
          autoFocus
          autoComplete="off"
          spellCheck={false}
          maxLength={256}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onInputKey}
          aria-describedby="search-help"
        />
      </form>
      <p id="search-help" className="muted">
        Words match anywhere in titles, on-screen text and speech. Use "exact phrases", prefix* and
        -word to exclude. Press ↓ to move to the results. Nothing leaves this computer.
      </p>
      <IndexStatus workerReady={workerReady} />
      <div className="search-layout">
        <aside aria-label="Filters" className="search-filters">
          {FACET_GROUPS.map((group) => {
            const selected = (effective[group.filter] as string[] | undefined) ?? [];
            const facets = data?.facets[group.facet] ?? [];
            const values = [
              ...facets,
              ...selected
                .filter((v) => !facets.some((f) => f.value === v))
                .map((value) => ({ value, count: 0 })),
            ];
            if (values.length === 0) return null;
            return (
              <fieldset key={group.facet}>
                <legend>{group.label}</legend>
                {values.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    className="facet"
                    aria-pressed={selected.includes(f.value)}
                    onClick={() => toggle(group.filter, f.value)}
                  >
                    {group.facet === "kind" ? (KIND_LABELS[f.value] ?? f.value) : f.value} (
                    {f.count})
                  </button>
                ))}
              </fieldset>
            );
          })}
          <fieldset>
            <legend>Confidence</legend>
            <select
              aria-label="Minimum confidence"
              value={effective.min_confidence ?? ""}
              onChange={(e) =>
                setNumber("min_confidence", e.target.value ? Number(e.target.value) : undefined)
              }
            >
              <option value="">Any</option>
              <option value="0.5">50% or more</option>
              <option value="0.8">80% or more</option>
              <option value="0.95">95% or more</option>
            </select>
          </fieldset>
          <fieldset>
            <legend>Date</legend>
            <label>
              From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>
              To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </label>
          </fieldset>
          <fieldset>
            <legend>Duration (seconds)</legend>
            <label>
              At least{" "}
              <input
                type="number"
                min={0}
                value={
                  effective.min_duration_ms !== undefined ? effective.min_duration_ms / 1000 : ""
                }
                onChange={(e) =>
                  setNumber(
                    "min_duration_ms",
                    e.target.value === "" ? undefined : Math.round(Number(e.target.value) * 1000),
                  )
                }
              />
            </label>
            <label>
              At most{" "}
              <input
                type="number"
                min={0}
                value={
                  effective.max_duration_ms !== undefined ? effective.max_duration_ms / 1000 : ""
                }
                onChange={(e) =>
                  setNumber(
                    "max_duration_ms",
                    e.target.value === "" ? undefined : Math.round(Number(e.target.value) * 1000),
                  )
                }
              />
            </label>
          </fieldset>
          {anyFilter && (
            <button
              type="button"
              onClick={() => {
                setFilters({});
                setFrom("");
                setTo("");
                setOffset(0);
              }}
            >
              Clear filters
            </button>
          )}
        </aside>
        <div className="search-results">
          {results.error && <p role="alert">{describeError(results.error)}</p>}
          {data && (
            <p role="status" className="muted">
              {data.total === 1 ? "1 result" : `${data.total} results`}
              {data.query.ignored.length > 0 ? ` · ignored ${data.query.ignored.join(" ")}` : ""}
            </p>
          )}
          {data && data.total === 0 && (
            <p className="muted">
              Nothing matches{query ? ` “${query}”` : ""}
              {anyFilter ? " with these filters" : ""}.
            </p>
          )}
          {data && data.items.length > 0 && (
            <ol ref={list} className="results" aria-label="Results">
              {data.items.map((item) => (
                <li key={item.key}>
                  <a className="result" href={resultHref(item)} onKeyDown={onResultKey}>
                    <ResultBody result={item} />
                  </a>
                  <AddToCollection result={item} collections={collections.data ?? []} />
                </li>
              ))}
            </ol>
          )}
          {data && data.total > PAGE && (
            <div className="row">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Previous
              </button>
              <span className="muted">
                {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
              </span>
              <button
                type="button"
                disabled={offset + PAGE >= data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </div>
          )}
        </div>
        <CollectionsPanel
          workerReady={workerReady}
          currentRule={query || anyFilter ? { version: 1, query, filters: effective } : null}
        />
      </div>
    </section>
  );
}
