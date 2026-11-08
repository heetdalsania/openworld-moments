// SPDX-License-Identifier: AGPL-3.0-or-later
// Collections (M26): manual lists and rule-based collections (saved searches). A rule
// is shown as plain sentences; each rule item explains why it matched.
import { useState } from "react";
import {
  type Collection,
  type CollectionRule,
  createCollection,
  deleteCollection,
  describeError,
  getCollection,
  listCollections,
  removeFromCollection,
} from "./api";
import { invalidate, useAction, useQuery } from "./query";
import { ResultBody, resultHref, resultTitle } from "./SearchResult";

const KIND_NAMES: Record<string, string> = {
  clip: "clips",
  session: "sessions",
  event: "events",
  transcript: "speech",
  project: "projects",
};

/** A rule as readable sentences: what it matches, never SQL. */
export function describeRule(rule: CollectionRule): string[] {
  const f = rule.filters;
  const parts: string[] = [];
  if (rule.query) parts.push(`Text matches ${rule.query}`);
  if (f.kinds?.length) parts.push(`Only ${f.kinds.map((k) => KIND_NAMES[k] ?? k).join(" or ")}`);
  if (f.event_types?.length) parts.push(`Label is ${f.event_types.join(" or ")}`);
  if (f.review_states?.length) parts.push(`Review state is ${f.review_states.join(" or ")}`);
  if (f.source_kinds?.length) parts.push(`Source is ${f.source_kinds.join(" or ")}`);
  if (f.session_ids?.length) parts.push(`In ${f.session_ids.length} chosen session(s)`);
  if (f.min_confidence !== undefined) {
    parts.push(`Confidence at least ${Math.round(f.min_confidence * 100)}%`);
  }
  if (f.occurred_from) parts.push(`On or after ${f.occurred_from.slice(0, 10)}`);
  if (f.occurred_to) parts.push(`On or before ${f.occurred_to.slice(0, 10)}`);
  if (f.min_duration_ms !== undefined) parts.push(`At least ${f.min_duration_ms / 1000} s long`);
  if (f.max_duration_ms !== undefined) parts.push(`At most ${f.max_duration_ms / 1000} s long`);
  return parts;
}

function CollectionDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [offset, setOffset] = useState(0);
  const page = useQuery<Collection>(`collection:${id}:${offset}`, () => getCollection(id, offset));
  const remove = useAction(async (itemId: number) => {
    await removeFromCollection(id, itemId);
    invalidate(`collection:${id}`, "collection:list");
  });
  const drop = useAction(async () => {
    await deleteCollection(id);
    invalidate("collection:list");
    onClose();
  });
  const [confirm, setConfirm] = useState(false);
  const failure = remove.error ?? drop.error;
  const data = page.data;
  if (page.error) return <p role="alert">{describeError(page.error)}</p>;
  if (!data) return <p role="status">Loading collection…</p>;
  return (
    <div className="collection-detail">
      <h3>{data.name}</h3>
      {data.rule ? (
        <>
          <p className="muted">Fills itself from the library using this rule:</p>
          <ul aria-label="Rule">
            {describeRule(data.rule).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">
          Items you added by hand. Removing a clip, event or transcript removes it here too.
        </p>
      )}
      <p role="status" className="muted">
        {data.total === 1 ? "1 item" : `${data.total} items`}
      </p>
      <ol className="results" aria-label={`Items in ${data.name}`}>
        {data.items.map((item) => (
          <li key={item.key}>
            <a className="result" href={resultHref(item)}>
              <ResultBody result={item} />
            </a>
            {item.reasons && (
              <ul className="reasons" aria-label={`Why ${resultTitle(item)} matched`}>
                {item.reasons.map((r) => (
                  <li key={r.criterion}>{r.detail}</li>
                ))}
              </ul>
            )}
            {item.item_id !== undefined && (
              <button
                type="button"
                disabled={remove.busy}
                onClick={() => {
                  if (item.item_id !== undefined) void remove.run(item.item_id);
                }}
              >
                Remove {resultTitle(item)} from {data.name}
              </button>
            )}
          </li>
        ))}
      </ol>
      {data.total > 50 && (
        <div className="row">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + 50 >= data.total}
            onClick={() => setOffset(offset + 50)}
          >
            Next
          </button>
        </div>
      )}
      {failure && <p role="alert">{describeError(failure)}</p>}
      <div className="row">
        <button type="button" onClick={onClose}>
          Back to collections
        </button>
        {confirm ? (
          <>
            <button
              type="button"
              className="danger"
              disabled={drop.busy}
              onClick={() => void drop.run()}
            >
              Delete {data.name}
            </button>
            <button type="button" onClick={() => setConfirm(false)}>
              Keep it
            </button>
          </>
        ) : (
          <button type="button" onClick={() => setConfirm(true)}>
            Delete collection…
          </button>
        )}
      </div>
    </div>
  );
}

export function CollectionsPanel({
  workerReady,
  currentRule,
}: {
  workerReady: boolean;
  currentRule: CollectionRule | null;
}) {
  const collections = useQuery(workerReady ? "collection:list" : null, listCollections);
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState("");
  const create = useAction(async (rule: CollectionRule | null) => {
    const created = await createCollection(name.trim(), rule ?? undefined);
    setName("");
    invalidate("collection:list");
    setOpen(created.id);
  });
  if (open) {
    return (
      <aside className="collections" aria-label="Collections">
        <CollectionDetail id={open} onClose={() => setOpen(null)} />
      </aside>
    );
  }
  const valid = name.trim().length > 0 && name.trim().length <= 80;
  return (
    <aside className="collections" aria-label="Collections">
      <h2>Collections</h2>
      {collections.error && <p role="alert">{describeError(collections.error)}</p>}
      {collections.data && collections.data.length === 0 && (
        <p className="muted">
          No collections yet. Make a list by hand, or save this search as a rule.
        </p>
      )}
      <ul className="collection-list">
        {(collections.data ?? []).map((c) => (
          <li key={c.id}>
            <button type="button" onClick={() => setOpen(c.id)}>
              {c.name}
            </button>{" "}
            <span className="muted">
              {c.kind === "rule"
                ? "rule"
                : `${c.item_count ?? 0} item${c.item_count === 1 ? "" : "s"}`}
            </span>
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) void create.run(null);
        }}
      >
        <label>
          New collection name{" "}
          <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="row">
          <button type="submit" disabled={!valid || create.busy || !workerReady}>
            Create list
          </button>
          <button
            type="button"
            disabled={!valid || !currentRule || create.busy || !workerReady}
            onClick={() => void create.run(currentRule)}
          >
            Save search as rule
          </button>
        </div>
      </form>
      {currentRule && (
        <p className="muted">
          A rule saves: {describeRule(currentRule).join("; ") || "everything"}.
        </p>
      )}
      {create.error && <p role="alert">{describeError(create.error)}</p>}
    </aside>
  );
}
