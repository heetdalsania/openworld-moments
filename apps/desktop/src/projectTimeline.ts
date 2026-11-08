// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  load,
  type EditorProject,
  type EventReview,
  type Session,
} from "@openworld-moments/contracts";
import { buildTimeline, type Rational, type Timeline } from "./timeline";

/** Preserve cut identity even when several segments reference the same original. */
export function projectTimeline(
  document: EditorProject,
  rates: Record<string, Rational> = {},
): Timeline {
  load("editor-project", document);
  const cuts = document.project.tracks[0]?.segments ?? [];
  const segments = cuts.map((s, index) => ({
    key: s.id,
    index,
    assetId: s.asset_id,
    sourceInMs: s.source_in_ms,
    sourceOutMs: s.source_out_ms,
    virtualStartMs: s.timeline_start_ms,
    virtualEndMs: s.timeline_start_ms + s.source_out_ms - s.source_in_ms,
    hiddenMs: 0,
    revealedDuplicateMs: 0,
  }));
  return {
    members: cuts.map((s) => ({
      assetId: s.asset_id,
      durationMs: s.source_out_ms,
      overlapMs: 0,
      ...(rates[s.asset_id] ? { frameRate: rates[s.asset_id] } : {}),
    })),
    segments,
    durationMs: segments.at(-1)?.virtualEndMs ?? 0,
    reveal: false,
  };
}

export interface ProjectMarker {
  key: string;
  atMs: number;
  label: string;
  detail: string;
}
/** Only current reviewed context, remapped via source ranges into every retained cut. */
export function projectMarkers(
  document: EditorProject,
  session: Session,
  review: EventReview,
): ProjectMarker[] {
  if (document.project.session_id !== session.id || review.session_id !== session.id) return [];
  const source = buildTimeline(
    session.assets.map((s) => ({
      assetId: s.asset_id,
      durationMs: s.duration_ms,
      overlapMs: s.overlap_with_previous_ms ?? 0,
    })),
  );
  if (source.durationMs !== review.duration_ms) return [];
  const markers: ProjectMarker[] = [];
  for (const item of review.items) {
    if (item.status !== "current" || item.effective.review_state === "rejected") continue;
    const event = item.effective;
    for (const clip of source.segments) {
      const a = Math.max(event.start_ms, clip.virtualStartMs);
      const b = Math.min(event.end_ms, clip.virtualEndMs);
      if (a >= b) continue;
      const sourceStart = clip.sourceInMs + a - clip.virtualStartMs;
      const sourceEnd = clip.sourceInMs + b - clip.virtualStartMs;
      for (const cut of document.project.tracks[0]?.segments ?? []) {
        if (cut.asset_id !== clip.assetId) continue;
        const from = Math.max(cut.source_in_ms, sourceStart),
          to = Math.min(cut.source_out_ms, sourceEnd);
        if (from >= to) continue;
        markers.push({
          key: `${event.id}:${cut.id}`,
          atMs: cut.timeline_start_ms + from - cut.source_in_ms,
          label: event.type.replaceAll("openworld.", "").replaceAll("_", " "),
          detail: `${Math.round(event.confidence * 100)}% confidence · ${event.source.kind} · ${event.evidence.length} evidence items · read-only`,
        });
      }
    }
  }
  return markers;
}

/** Local allocation only; IDs are explicit inputs to the M21 split command. */
export function newSegmentId(): string {
  const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return `seg_${Array.from(crypto.getRandomValues(new Uint8Array(26)), (n) => alphabet[n & 31]).join("")}`;
}
