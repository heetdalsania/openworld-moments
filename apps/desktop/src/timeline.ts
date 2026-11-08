// SPDX-License-Identifier: AGPL-3.0-or-later
// Virtual session timeline (M13): one continuous "unique time" across a session's
// ordered clips, hiding footage a clip repeats from the previous one (M12 overlaps).
//
// Model: each clip contributes one segment, its source range [hidden, duration), where
// `hidden` is the applied overlap with the previous clip (0 for the first clip, and for
// every clip while duplicates are revealed). Segments play back to back: real-world
// gaps between recordings are not played. All times are integer milliseconds, so a
// virtual -> source -> virtual round trip is exact for any frame rate.

export interface Rational {
  num: number;
  den: number;
}

export interface TimelineMember {
  assetId: string;
  durationMs: number;
  /** Applied overlap with the previous clip (session member `overlap_with_previous_ms`). */
  overlapMs: number;
  overlapConfidence?: number;
  /** Average frame rate (used for frame stepping; VFR clips use their average). */
  frameRate?: Rational;
}

export interface Segment {
  /** Editor cut identity; sessions continue to use their unique asset ID. */
  key?: string;
  index: number;
  assetId: string;
  /** First and end (exclusive) source time played, ms. */
  sourceInMs: number;
  sourceOutMs: number;
  virtualStartMs: number;
  virtualEndMs: number;
  /** Repeated footage at this clip's start hidden from playback (0 when revealed). */
  hiddenMs: number;
  /** Repeated footage at this clip's start that is shown because duplicates are revealed. */
  revealedDuplicateMs: number;
  overlapConfidence?: number;
}

export interface Timeline {
  members: readonly TimelineMember[];
  segments: readonly Segment[];
  durationMs: number;
  reveal: boolean;
}

export interface SourcePosition {
  segment: Segment;
  /** Time within the clip, ms. */
  sourceMs: number;
}

const DEFAULT_FRAME_MS = 1000 / 30;

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}

/** Build the virtual timeline. `reveal` shows repeated footage instead of hiding it. */
export function buildTimeline(
  members: readonly TimelineMember[],
  { reveal = false }: { reveal?: boolean } = {},
): Timeline {
  const segments: Segment[] = [];
  let position = 0;
  members.forEach((member, index) => {
    const duration = Math.max(0, Math.round(member.durationMs));
    const overlap = index === 0 ? 0 : clamp(Math.round(member.overlapMs), 0, duration);
    const hidden = reveal ? 0 : overlap;
    const length = duration - hidden;
    segments.push({
      index,
      assetId: member.assetId,
      sourceInMs: hidden,
      sourceOutMs: duration,
      virtualStartMs: position,
      virtualEndMs: position + length,
      hiddenMs: hidden,
      revealedDuplicateMs: reveal ? overlap : 0,
      ...(member.overlapConfidence !== undefined
        ? { overlapConfidence: member.overlapConfidence }
        : {}),
    });
    position += length;
  });
  return { members, segments, durationMs: position, reveal };
}

function playable(timeline: Timeline): Segment[] {
  return timeline.segments.filter((s) => s.virtualEndMs > s.virtualStartMs);
}

/**
 * Which clip, and where in it, plays at virtual time `virtualMs`. Segments are
 * half-open: a boundary belongs to the clip that starts there. The very end maps to
 * the last clip's end. Null for an empty timeline.
 */
export function toSource(timeline: Timeline, virtualMs: number): SourcePosition | null {
  const segments = playable(timeline);
  const last = segments[segments.length - 1];
  if (!last) return null;
  const v = clamp(Math.round(virtualMs), 0, timeline.durationMs);
  if (v >= last.virtualEndMs) return { segment: last, sourceMs: last.sourceOutMs };
  let lo = 0;
  let hi = segments.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    const candidate = segments[mid];
    if (candidate && candidate.virtualStartMs <= v) lo = mid;
    else hi = mid - 1;
  }
  const segment = segments[lo] ?? last;
  return { segment, sourceMs: segment.sourceInMs + (v - segment.virtualStartMs) };
}

export interface VirtualPosition {
  virtualMs: number;
  /** False when the source time was hidden repeated footage, mapped to the identical
   * moment in an earlier clip. */
  exact: boolean;
}

/**
 * Where source time `sourceMs` of clip `index` appears on the virtual timeline. Hidden
 * repeated footage maps to the same moment in the previous clip (B starts at
 * `duration(A) - overlap` in A). Null outside the clip.
 */
export function toVirtual(
  timeline: Timeline,
  index: number,
  sourceMs: number,
): VirtualPosition | null {
  const segment = timeline.segments[index];
  if (!segment) return null;
  const t = Math.round(sourceMs);
  if (t < 0 || t > segment.sourceOutMs || (segment.key && t < segment.sourceInMs)) return null;
  if (t >= segment.sourceInMs) {
    return { virtualMs: segment.virtualStartMs + (t - segment.sourceInMs), exact: true };
  }
  const previous = timeline.segments[index - 1];
  if (!previous) return null;
  const inPrevious = previous.sourceOutMs - segment.hiddenMs + t;
  const mapped = toVirtual(timeline, index - 1, inPrevious);
  return mapped ? { virtualMs: mapped.virtualMs, exact: false } : null;
}

/** Index of a clip on the timeline by asset ID, or -1. */
export function indexOf(timeline: Timeline, assetId: string): number {
  return timeline.segments.findIndex((s) => s.assetId === assetId);
}

/** One frame of a clip, ms (from its average frame rate; 30 fps when unknown). */
export function frameMs(member: TimelineMember | undefined): number {
  const rate = member?.frameRate;
  if (!rate || rate.num <= 0 || rate.den <= 0) return DEFAULT_FRAME_MS;
  return (1000 * rate.den) / rate.num;
}

/**
 * The virtual time one frame forward (+1) or back (-1). Frames are those of the clip
 * playing at `virtualMs`; stepping past a boundary lands on the neighbouring clip's
 * first (or last) unique frame.
 */
export function stepFrame(timeline: Timeline, virtualMs: number, direction: 1 | -1): number {
  const here = toSource(timeline, virtualMs);
  if (!here) return 0;
  const step = frameMs(timeline.members[here.segment.index]);
  const target = here.sourceMs + direction * step;
  const { segment } = here;
  if (target >= segment.sourceInMs && target < segment.sourceOutMs) {
    return Math.round(segment.virtualStartMs + (target - segment.sourceInMs));
  }
  const segments = playable(timeline);
  const position = segments.indexOf(segment);
  if (direction > 0) {
    const next = segments[position + 1];
    return next ? next.virtualStartMs : timeline.durationMs;
  }
  const previous = segments[position - 1];
  if (!previous) return 0;
  const lastFrame = frameMs(timeline.members[previous.index]);
  return Math.max(previous.virtualStartMs, Math.round(previous.virtualEndMs - lastFrame));
}

/** Virtual times where a new clip starts (excluding 0). */
export function boundaries(timeline: Timeline): number[] {
  return playable(timeline)
    .slice(1)
    .map((s) => s.virtualStartMs);
}

/** The next (or previous) clip boundary from `virtualMs`, for keyboard navigation. */
export function nearestBoundary(timeline: Timeline, virtualMs: number, direction: 1 | -1): number {
  const marks = [0, ...boundaries(timeline), timeline.durationMs];
  if (direction > 0) return marks.find((m) => m > virtualMs + 1) ?? timeline.durationMs;
  return [...marks].reverse().find((m) => m < virtualMs - 1) ?? 0;
}

/** Total repeated footage across the session (hidden or revealed), ms. */
export function repeatedMs(timeline: Timeline): number {
  return timeline.segments.reduce((sum, s) => sum + s.hiddenMs + s.revealedDuplicateMs, 0);
}
