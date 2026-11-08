// SPDX-License-Identifier: AGPL-3.0-or-later
// One search result (M26): where it opens and how it reads. Text segments render as
// text with <mark> for matched words, never as HTML.
import type { SearchResult } from "./api";
import { formatDuration } from "./media";
import { routeHref } from "./route";

export const KIND_LABELS: Record<string, string> = {
  clip: "Clip",
  session: "Session",
  event: "Event",
  transcript: "Speech",
  project: "Project",
};
/** Where a result opens: sessions and events seek to their unique-session time. */
export function resultHref(result: SearchResult): string {
  const at = result.range?.start_ms;
  switch (result.kind) {
    case "clip":
      return routeHref({ view: "asset", id: result.asset_id ?? "", ...(at ? { at } : {}) });
    case "project":
      return routeHref({ view: "project", id: result.project_id ?? "" });
    case "session":
      return routeHref({ view: "session", id: result.session_id ?? "" });
    default:
      return routeHref({
        view: "session",
        id: result.session_id ?? "",
        ...(at !== undefined ? { at } : {}),
      });
  }
}

export function Segments({ segments }: { segments: SearchResult["title"] }) {
  return (
    <>
      {segments.map((s, i) =>
        s.match ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>,
      )}
    </>
  );
}

function plain(segments: SearchResult["title"]): string {
  return segments.map((s) => s.text).join("");
}

export function resultTitle(result: SearchResult): string {
  return plain(result.title) || KIND_LABELS[result.kind] || result.kind;
}

export function ResultBody({ result }: { result: SearchResult }) {
  const range = result.range;
  const meta = [
    range && result.kind !== "session" && result.kind !== "clip"
      ? `${formatDuration(range.start_ms)}–${formatDuration(range.end_ms)}`
      : null,
    result.duration_ms !== undefined && (result.kind === "clip" || result.kind === "session")
      ? formatDuration(result.duration_ms)
      : null,
    result.confidence !== undefined ? `${Math.round(result.confidence * 100)}% confidence` : null,
    result.review_state ?? null,
    result.source_kind ?? null,
    result.occurred_at ? result.occurred_at.slice(0, 10) : null,
  ].filter(Boolean);
  return (
    <>
      <span className="result-kind">{KIND_LABELS[result.kind]}</span>{" "}
      <strong className="result-title">
        <Segments
          segments={
            result.title.length ? result.title : [{ text: resultTitle(result), match: false }]
          }
        />
      </strong>
      {result.snippet.length > 0 && (
        <span className="result-snippet">
          <Segments segments={result.snippet} />
        </span>
      )}
      <span className="muted result-meta">
        {meta.join(" · ")}
        {result.matched_in.length > 0 ? ` · matched in ${result.matched_in.join(" and ")}` : ""}
      </span>
    </>
  );
}
