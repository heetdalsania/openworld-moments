// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import {
  alignSessions,
  describeError,
  listSessions,
  mergeSessions,
  recomputeSessions,
  type Session,
} from "./api";
import { upsertJob } from "./jobs";
import { formatDuration } from "./media";
import { invalidate, useAction, useQuery } from "./query";
import { navigate, routeHref } from "./route";

/** Unique (played) duration of a session: every clip minus the footage it repeats. */
export function uniqueDurationMs(session: Session): number {
  return session.assets.reduce(
    (sum, m, i) => sum + m.duration_ms - (i > 0 ? (m.overlap_with_previous_ms ?? 0) : 0),
    0,
  );
}

const STATE_TEXT: Record<Session["review_state"], string> = {
  unreviewed: "Suggested",
  corrected: "Edited by you",
  confirmed: "Confirmed",
};

interface CardProps {
  session: Session;
  selected: boolean;
  onSelect: (selected: boolean) => void;
}

function SessionCard({ session, selected, onSelect }: CardProps) {
  const repeated = session.assets.reduce((sum, m) => sum + (m.overlap_with_previous_ms ?? 0), 0);
  const confidence = session.grouping_confidence;
  return (
    <li className="session-item">
      <label className="check select">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          aria-label={`Select ${session.title} to merge`}
        />
      </label>
      <a className="card session-card" href={routeHref({ view: "session", id: session.id })}>
        <span className="card-title">{session.title}</span>
        <span className="muted">
          {session.assets.length} {session.assets.length === 1 ? "clip" : "clips"} ·{" "}
          {formatDuration(uniqueDurationMs(session))}
          {repeated > 0 ? ` · ${formatDuration(repeated)} repeated footage hidden` : ""}
        </span>
        <span className="badges">
          <span className="badge">{STATE_TEXT[session.review_state]}</span>
          {confidence !== null && confidence !== undefined && (
            <span className={confidence < 0.4 ? "badge warn" : "badge"}>
              Grouping confidence {Math.round(confidence * 100)}%
            </span>
          )}
        </span>
      </a>
    </li>
  );
}

/** Candidate play sessions (M11), newest first. */
export function SessionsView() {
  const sessions = useQuery("sessions:list", listSessions);
  const group = useAction(async () => upsertJob(await recomputeSessions()));
  const align = useAction(async () => upsertJob(await alignSessions()));
  const [selected, setSelected] = useState<string[]>([]);
  const merge = useAction(async () => {
    // Merge into the earliest selected session (the list is newest first).
    const order = (sessions.data ?? []).map((s) => s.id).filter((sid) => selected.includes(sid));
    const merged = await mergeSessions(order.reverse());
    setSelected([]);
    invalidate("sessions");
    navigate({ view: "session", id: merged.id });
  });
  const actionError = group.error ?? align.error ?? merge.error;

  return (
    <section className="view" aria-labelledby="sessions-heading">
      <div className="view-head">
        <h1 id="sessions-heading">Sessions</h1>
        <div className="row">
          <button type="button" disabled={group.busy} onClick={() => void group.run()}>
            Group clips into sessions
          </button>
          <button type="button" disabled={align.busy} onClick={() => void align.run()}>
            Find repeated footage
          </button>
          <button
            type="button"
            disabled={selected.length < 2 || merge.busy}
            onClick={() => void merge.run()}
          >
            Merge selected{selected.length >= 2 ? ` (${selected.length})` : ""}
          </button>
        </div>
      </div>
      <p className="muted">
        Sessions are suggestions built from capture times, sources, and formats. Grouping never
        changes or moves your files; your edits to a session are kept.
      </p>
      {actionError && <p role="alert">{describeError(actionError)}</p>}
      {sessions.loading && !sessions.data && <p role="status">Loading sessions…</p>}
      {sessions.error && (
        <div role="alert" className="notice-box">
          <p>Sessions could not be loaded: {describeError(sessions.error)}</p>
          <button type="button" onClick={sessions.refetch}>
            Try again
          </button>
        </div>
      )}
      {sessions.data?.length === 0 && (
        <div className="empty">
          <h2>No sessions yet</h2>
          <p>Import some clips, then group them into play sessions.</p>
        </div>
      )}
      {sessions.data && sessions.data.length > 0 && (
        <ul className="grid sessions" aria-label={`${sessions.data.length} sessions`}>
          {sessions.data.map((s) => (
            <SessionCard
              key={s.id}
              session={s}
              selected={selected.includes(s.id)}
              onSelect={(on) =>
                setSelected((ids) => (on ? [...ids, s.id] : ids.filter((sid) => sid !== s.id)))
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}
