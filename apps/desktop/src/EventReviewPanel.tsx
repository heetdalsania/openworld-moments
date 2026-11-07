// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  addManualEvent,
  analyzeSession,
  listProfiles,
  describeError,
  eventReview,
  reviewEvent,
  type EventReviewItem,
} from "./api";
import { invalidate, useAction, useQuery } from "./query";
import { useJobs, upsertJob, isActive } from "./jobs";
import { buildTimeline, toSource, toVirtual, type Timeline } from "./timeline";

function clock(ms: number): string {
  return `${(ms / 1000).toFixed(2)}s`;
}

export function EventReviewPanel({
  sessionId,
  timeline,
  virtualMs,
  onSeek,
}: {
  sessionId: string;
  timeline: Timeline;
  virtualMs: number;
  onSeek: (ms: number) => void;
}) {
  const [offset, setOffset] = useState(0);
  const query = useQuery(`sessions:${sessionId}:review:${offset}`, () =>
    eventReview(sessionId, offset),
  );
  const profiles = useQuery("event-review:profiles", listProfiles);
  const [profile, setProfile] = useState("");
  const [selected, select] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [label, setLabel] = useState("openworld.manual");
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState("1");
  const jobs = useJobs();
  const latest = jobs.jobs.find(
    (j) =>
      j.kind === "analyze" &&
      (j.params as { session_id?: string } | undefined)?.session_id === sessionId,
  );
  const running = latest !== undefined && isActive(latest);
  const [draft, setDraft] = useState({ revision: 0, layout: "" });
  const refresh = useCallback(() => invalidate(`sessions:${sessionId}:review`), [sessionId]);
  const action = useAction(async (operation: () => Promise<unknown>) => {
    try {
      await operation();
    } finally {
      refresh();
    }
  });
  useEffect(() => {
    refresh();
  }, [timeline, refresh]); // session relayout refreshes stale flags
  const item = query.data?.items.find((i) => i.original.id === selected);
  const fingerprint = JSON.stringify(
    timeline.members.map((m) => [m.assetId, m.durationMs, m.overlapMs]),
  );
  const [verified, setVerified] = useState({ fingerprint: "", key: "" });
  useEffect(() => {
    let cancelled = false;
    void Promise.resolve()
      .then(() => crypto.subtle.digest("SHA-256", new TextEncoder().encode(fingerprint)))
      .then((bytes) => {
        if (!cancelled)
          setVerified({
            fingerprint,
            key: Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join(""),
          });
      })
      .catch(() => {
        if (!cancelled) setVerified({ fingerprint, key: "" });
      });
    return () => {
      cancelled = true;
    };
  }, [fingerprint]);
  const synchronized =
    !query.loading &&
    verified.fingerprint === fingerprint &&
    verified.key === query.data?.layout_key;
  const current = item?.status === "current" && synchronized;
  const seekItem = (entry: EventReviewItem) => {
    if (entry.status !== "current" || !synchronized) return;
    const e = entry.effective;
    // Event times use unique session time. Revealing repeated footage changes
    // the playback timeline; round-trip through its source clip for marker seeks.
    // Corrected and manual times are already in the unique timeline. Map them
    // using an independently constructed unique layout below.
    onSeek(reviewToPlayback(timeline, e.start_ms));
  };
  const edit = (entry: EventReviewItem) => {
    setDraft({ revision: entry.revision, layout: query.data?.layout_key ?? "" });
    select(entry.original.id);
    setManual(false);
    setLabel(entry.effective.type);
    setStart(String(entry.effective.start_ms / 1000));
    setEnd(String(entry.effective.end_ms / 1000));
  };
  const change = (kind: "approve" | "reject" | "reset" | "correct") => {
    if (!item || !query.data) return;
    void action.run(() =>
      reviewEvent(sessionId, item.original.id, {
        layout_key: draft.layout,
        expected_revision: draft.revision,
        action: kind,
        ...(kind === "correct"
          ? {
              type: label,
              start_ms: Math.round(Number(start) * 1000),
              end_ms: Math.round(Number(end) * 1000),
            }
          : {}),
      }).then((updated) => {
        setDraft({ ...draft, revision: updated.revision });
        setLabel(updated.effective.type);
        setStart(String(updated.effective.start_ms / 1000));
        setEnd(String(updated.effective.end_ms / 1000));
      }),
    );
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!query.data) return;
    if (manual)
      void action.run(() =>
        addManualEvent(sessionId, {
          layout_key: draft.layout,
          type: label,
          start_ms: Math.round(Number(start) * 1000),
          end_ms: Math.round(Number(end) * 1000),
        }).then(() => {
          setManual(false);
        }),
      );
    else change("correct");
  };
  return (
    <section className="event-review" aria-labelledby="events-heading">
      <h2 id="events-heading">Event review</h2>
      <p className="warning" role="note">
        <strong>Game compatibility is unvalidated.</strong> Confidence is a heuristic. Audio events
        are supporting evidence, not highlights. Review visible footage before accepting an event.
      </p>
      <div className="row">
        <label>
          Detector profile{" "}
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="">Choose a profile</option>
            {profiles.data?.map((p) => (
              <option value={p.id} key={p.id}>
                {p.id}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={!profile || action.busy || running}
          onClick={() =>
            void action.run(async () => upsertJob(await analyzeSession(sessionId, profile)))
          }
        >
          Analyze events
        </button>
        <button onClick={refresh} disabled={query.loading}>
          Refresh events
        </button>
        <button
          disabled={!query.data || !synchronized || action.busy}
          onClick={() => {
            if (!query.data || !synchronized) return;
            setDraft({ revision: 0, layout: query.data.layout_key });
            setManual(true);
            select(null);
            setLabel("openworld.manual");
            const at = playbackToReview(timeline, virtualMs);
            setStart(String(at / 1000));
            setEnd(String(Math.min(query.data.duration_ms, at + 1000) / 1000));
          }}
        >
          Add event at playhead
        </button>
      </div>
      {running && (
        <p role="status">
          Analyzing events. Cancel or inspect progress in Background jobs. Refresh after completion.
        </p>
      )}
      {latest?.state === "failed" && (
        <p role="alert">
          {latest.error?.message ?? "Event analysis failed. Earlier results remain inspectable."}
        </p>
      )}
      {latest?.state === "cancelled" && (
        <p role="status">Event analysis cancelled. Completed observations are kept.</p>
      )}
      {profiles.error && <p role="alert">{describeError(profiles.error)}</p>}
      {query.loading && <p role="status">Loading event observations…</p>}
      {query.error && <p role="alert">{describeError(query.error)}</p>}
      {action.error && <p role="alert">{describeError(action.error)}</p>}
      {query.data && !query.data.total && (
        <p>No events yet. Choose a detector profile or add an event manually.</p>
      )}
      <div className="event-marker-track" role="group" aria-label="Events on session timeline">
        {query.data?.items
          .filter((e) => e.status === "current" && synchronized)
          .map((e) => (
            <button
              key={e.original.id}
              className={`event-marker ${e.effective.review_state}`}
              style={{
                left: `${(100 * reviewToPlayback(timeline, e.effective.start_ms)) / Math.max(1, timeline.durationMs)}%`,
              }}
              title={`${e.effective.type} at ${clock(e.effective.start_ms)}`}
              aria-label={`Review marker ${e.effective.type} at ${e.effective.start_ms} milliseconds`}
              onClick={() => {
                edit(e);
                seekItem(e);
              }}
            >
              ◆
            </button>
          ))}
      </div>
      {query.data && !query.loading && !synchronized && (
        <p role="status">
          Verifying event timing. If the session changed, refresh events before seeking or
          reviewing.
        </p>
      )}
      <ol className="event-lane" aria-label="Event markers">
        {query.data?.items.map((entry) => (
          <li key={entry.original.id}>
            <button
              disabled={entry.status !== "current" || !synchronized}
              onClick={() => seekItem(entry)}
              aria-label={`Seek ${entry.effective.type} at ${entry.effective.start_ms} milliseconds`}
            >
              {clock(entry.effective.start_ms)}–{clock(entry.effective.end_ms)}
            </button>{" "}
            <button onClick={() => edit(entry)} aria-pressed={selected === entry.original.id}>
              {entry.effective.type}
            </button>{" "}
            <span className="badge">{entry.effective.review_state}</span>
            {entry.status !== "current" && <span className="badge warn">{entry.status}</span>}
          </li>
        ))}
      </ol>
      {query.data && (
        <div className="row">
          <button
            disabled={!offset || query.loading}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Previous events
          </button>
          <span>
            {offset + query.data.items.length} of {query.data.total}
          </span>
          <button
            disabled={offset + query.data.items.length >= query.data.total || query.loading}
            onClick={() => setOffset(offset + 50)}
          >
            Next events
          </button>
        </div>
      )}
      {item && (
        <div className="evidence-inspector" aria-label="Event evidence">
          <h3>Evidence and provenance</h3>
          {item.status !== "current" && (
            <p role="note">
              {item.status === "superseded"
                ? "Re-analysis replaced this observation. Your decisions remain here; review the new observations separately."
                : "The original timing is unverified for this session layout. Analyze again before reviewing."}
            </p>
          )}
          <p>
            Original: {item.original.type}, {clock(item.original.start_ms)}–
            {clock(item.original.end_ms)} · confidence {Math.round(item.original.confidence * 100)}%
            · revision {item.revision}
          </p>
          {item.original.attributes.spoiler_risk === true && (
            <p className="warning">Mission text may reveal spoilers.</p>
          )}
          <h4>Producer, profile and tools</h4>
          <dl className="event-provenance">
            {Object.entries(item.original.source).flatMap(([name, value]) =>
              name === "tool_versions" && value && typeof value === "object" ? (
                Object.entries(value).map(([tool, version]) => (
                  <div key={`tool-${tool}`}>
                    <dt>{tool.replaceAll("_", " ")}</dt>
                    <dd>{String(version)}</dd>
                  </div>
                ))
              ) : (
                <div key={name}>
                  <dt>{name.replaceAll("_", " ")}</dt>
                  <dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
                </div>
              ),
            )}
          </dl>
          <h4>Supporting evidence</h4>
          <ul>
            {item.original.evidence.map((e, i) => (
              <li key={i}>
                <strong>{e.kind.replaceAll("_", " ")}</strong> · {Math.round(e.score * 100)}%
                confidence
                {"text" in e && <p>{e.text}</p>}
                {"frame_ms" in e && e.frame_ms !== undefined && (
                  <span> · source sample {clock(e.frame_ms)}</span>
                )}
                {"frames" in e && <span> · {e.frames} supporting frames</span>}
                {"region" in e && (
                  <span> · crop [{e.region.map((v) => `${Math.round(v * 100)}%`).join(", ")}]</span>
                )}
                {"role" in e && <span> · supporting evidence</span>}
              </li>
            ))}
          </ul>
          <details>
            <summary>Original evidence and attributes</summary>
            <pre>
              {JSON.stringify(
                { evidence: item.original.evidence, attributes: item.original.attributes },
                null,
                2,
              )}
            </pre>
          </details>
          <div className="row">
            <button disabled={!current || action.busy} onClick={() => change("approve")}>
              Approve event
            </button>
            <button disabled={!current || action.busy} onClick={() => change("reject")}>
              Reject event
            </button>
            <button disabled={!current || action.busy} onClick={() => change("reset")}>
              Reset review
            </button>
          </div>
          <details>
            <summary>Decision history ({item.revision})</summary>
            {item.history_truncated && (
              <p>Showing the latest 20 decisions. Earlier decisions remain in the library.</p>
            )}
            <ol>
              {item.history.map((h) => (
                <li key={h.revision}>
                  {h.revision}: {h.state} · {h.type} · {clock(h.start_ms)}–{clock(h.end_ms)} ·{" "}
                  {h.created_at}
                </li>
              ))}
            </ol>
          </details>
        </div>
      )}
      {(manual || item) && (
        <form onSubmit={submit}>
          <h3>{manual ? "Manual event" : "Correct label or interval"}</h3>
          <p>
            Times use the unique session timeline, with repeated footage hidden. The original
            observation stays unchanged.
          </p>
          <label>
            Event type{" "}
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              required
              pattern="[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+"
              maxLength={128}
            />
          </label>
          <label>
            Start seconds{" "}
            <input
              type="number"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              min="0"
              step="0.001"
              required
            />
          </label>
          <label>
            End seconds{" "}
            <input
              type="number"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              min="0"
              step="0.001"
              required
            />
          </label>
          <button disabled={action.busy || !synchronized || (!manual && !current)}>
            {manual ? "Save manual event" : "Save correction"}
          </button>
        </form>
      )}
    </section>
  );
}

// Preserve unique-session coordinates even while playback reveals duplicated ranges.
export function playbackToReview(timeline: Timeline, ms: number): number {
  const source = toSource(timeline, ms);
  if (!source) return 0;
  const unique = buildTimeline(timeline.members);
  return toVirtual(unique, source.segment.index, source.sourceMs)?.virtualMs ?? 0;
}
export function reviewToPlayback(timeline: Timeline, ms: number): number {
  const source = toSource(buildTimeline(timeline.members), ms);
  if (!source) return 0;
  return toVirtual(timeline, source.segment.index, source.sourceMs)?.virtualMs ?? 0;
}
