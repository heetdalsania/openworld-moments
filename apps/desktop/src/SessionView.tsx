// SPDX-License-Identifier: AGPL-3.0-or-later
// One session as a single continuous timeline (M13): clips play back to back, footage a
// later clip repeats is skipped, and every moment stays traceable to its source clip.
import {
  type KeyboardEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  type AssetDerivedMedia,
  type AssetOverlap,
  confirmSession,
  describeError,
  getAsset,
  getDerived,
  type MediaAsset,
  removeFromSession,
  reorderSession,
  type Session,
  sessionOverlaps,
  getSession,
  setOverlap,
  splitSession,
} from "./api";
import { formatDuration, mediaUrl, thumbnailUrl } from "./media";
import { type PlayerState, SessionPlayer } from "./player";
import { invalidate, useAction, useQuery } from "./query";
import { routeHref } from "./route";
import { EventReviewPanel } from "./EventReviewPanel";
import { CreateProject } from "./CreateProject";
import { SegmentWave } from "./TimelineWave";
import { TranscriptPanel } from "./TranscriptPanel";
import {
  buildTimeline,
  frameMs,
  nearestBoundary,
  repeatedMs,
  type Timeline,
  type TimelineMember,
  toSource,
} from "./timeline";

type Artifact = AssetDerivedMedia["artifacts"][number];

/** What playback needs to know about one clip. */
export interface MemberMedia {
  asset: MediaAsset;
  /** Playback copy when ready, else the original; null when nothing can play. */
  url: string | null;
  usesProxy: boolean;
  filmstrip: number[];
  waveform: boolean;
}

function playable(artifact: Artifact | undefined): boolean {
  return artifact?.status === "ready" || artifact?.status === "stale";
}

async function loadMember(assetId: string): Promise<MemberMedia> {
  const [asset, derived] = await Promise.all([
    getAsset(assetId),
    getDerived(assetId).catch(() => undefined),
  ]);
  const artifacts = derived?.artifacts ?? [];
  const proxy = artifacts.find((a) => a.kind === "proxy");
  const filmstrip = artifacts.find((a) => a.kind === "filmstrip");
  const waveform = artifacts.find((a) => a.kind === "waveform");
  const usesProxy = playable(proxy);
  const originalOk = !asset.missing_at;
  return {
    asset,
    url: usesProxy ? mediaUrl(assetId, "proxy") : originalOk ? mediaUrl(assetId, "original") : null,
    usesProxy,
    filmstrip: playable(filmstrip) ? (filmstrip?.filmstrip?.times_ms ?? []) : [],
    waveform: playable(waveform),
  };
}

export async function loadMembers(assetIds: string[]): Promise<Record<string, MemberMedia>> {
  const loaded = await Promise.all(assetIds.map(loadMember));
  return Object.fromEntries(assetIds.map((id, i) => [id, loaded[i] as MemberMedia]));
}

/** `m:ss.cc` (or `h:mm:ss.cc`): precise enough to talk about single frames. */
export function formatClock(ms: number): string {
  const clamped = Math.max(0, Math.round(ms));
  const centis = Math.floor((clamped % 1000) / 10);
  return `${formatDuration(Math.floor(clamped / 1000) * 1000)}.${String(centis).padStart(2, "0")}`;
}

export function timelineMembers(
  session: Session,
  media: Record<string, MemberMedia> | undefined,
): TimelineMember[] {
  return session.assets.map((m) => {
    const video = media?.[m.asset_id]?.asset.video;
    const frameRate = video?.average_frame_rate ?? video?.frame_rate;
    return {
      assetId: m.asset_id,
      durationMs: m.duration_ms,
      overlapMs: m.order_index > 0 ? (m.overlap_with_previous_ms ?? 0) : 0,
      ...(m.alignment_confidence !== undefined
        ? { overlapConfidence: m.alignment_confidence }
        : {}),
      ...(frameRate ? { frameRate } : {}),
    };
  });
}

function percent(confidence: number | undefined): string {
  return confidence === undefined ? "" : `${Math.round(confidence * 100)}%`;
}

const STATE_TEXT: Record<Session["review_state"], string> = {
  unreviewed: "Suggested",
  corrected: "Edited by you",
  confirmed: "Confirmed",
};

interface TrackProps {
  timeline: Timeline;
  media: Record<string, MemberMedia> | undefined;
  virtualMs: number;
  onSeek: (virtualMs: number) => void;
}

/** Clips laid end to end, with boundaries, repeated footage, thumbnails, and audio. */
function Track({ timeline, media, virtualMs, onSeek }: TrackProps) {
  const total = Math.max(1, timeline.durationMs);
  const seekAt = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    onSeek(Math.round(((event.clientX - rect.left) / rect.width) * timeline.durationMs));
  };
  return (
    <div className="track">
      {/* The pointer target; keyboard users have the position slider and shortcuts. */}
      <div className="track-lane" onClick={seekAt} aria-hidden="true">
        {timeline.segments.map((segment) => {
          const width = ((segment.virtualEndMs - segment.virtualStartMs) / total) * 100;
          const name = media?.[segment.assetId]?.asset.original_name ?? `Clip ${segment.index + 1}`;
          const shownTimes = (media?.[segment.assetId]?.filmstrip ?? [])
            .map((t, i) => [t, i + 1] as const)
            .filter(([t]) => t >= segment.sourceInMs && t < segment.sourceOutMs);
          return (
            <div
              key={segment.assetId}
              className="track-segment"
              style={{ width: `${width}%` }}
              title={name}
            >
              {segment.revealedDuplicateMs > 0 && (
                <div
                  className="track-duplicate"
                  style={{
                    width: `${(segment.revealedDuplicateMs / Math.max(1, segment.virtualEndMs - segment.virtualStartMs)) * 100}%`,
                  }}
                />
              )}
              <div className="track-thumbs">
                {shownTimes.map(([t, n]) => (
                  <img key={t} src={thumbnailUrl(segment.assetId, n)} alt="" loading="lazy" />
                ))}
              </div>
              {media?.[segment.assetId]?.waveform && (
                <SegmentWave segment={segment} durationMs={timeline.durationMs} />
              )}
              {segment.hiddenMs > 0 && <span className="track-hidden" />}
            </div>
          );
        })}
        <div className="track-head" style={{ left: `${(virtualMs / total) * 100}%` }} />
      </div>
      <ol className="track-legend" aria-label="Clip boundaries">
        {timeline.segments.map((segment) => {
          const name = media?.[segment.assetId]?.asset.original_name ?? `Clip ${segment.index + 1}`;
          const empty = segment.virtualEndMs === segment.virtualStartMs;
          return (
            <li key={segment.assetId}>
              <button type="button" onClick={() => onSeek(segment.virtualStartMs)} disabled={empty}>
                {formatClock(segment.virtualStartMs)} · {name}
              </button>
              {segment.hiddenMs > 0 && (
                <span
                  className="badge"
                  title="Repeated footage at the start of this clip is skipped"
                >
                  {formatClock(segment.hiddenMs)} repeated footage hidden
                  {segment.overlapConfidence !== undefined
                    ? ` · ${percent(segment.overlapConfidence)} sure`
                    : ""}
                </span>
              )}
              {segment.revealedDuplicateMs > 0 && (
                <span className="badge warn">
                  First {formatClock(segment.revealedDuplicateMs)} repeats the previous clip
                </span>
              )}
              {empty && <span className="badge">Entirely repeated footage: skipped</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function overlapSource(overlaps: AssetOverlap[] | undefined, previous: string, assetId: string) {
  return overlaps?.find((o) => o.asset_a === previous && o.asset_b === assetId);
}

interface ClipListProps {
  session: Session;
  media: Record<string, MemberMedia> | undefined;
  overlaps: AssetOverlap[] | undefined;
  timeline: Timeline;
  onSeek: (virtualMs: number) => void;
}

/** Per-clip corrections: order, split, unrelated clips, and repeated-footage overrides. */
function ClipList({ session, media, overlaps, timeline, onSeek }: ClipListProps) {
  const ids = session.assets.map((m) => m.asset_id);
  const correct = useAction(async (change: () => Promise<unknown>) => {
    await change();
    invalidate("sessions");
  });
  const move = (index: number, by: -1 | 1) => {
    const order = [...ids];
    const [moved] = order.splice(index, 1);
    if (moved === undefined) return;
    order.splice(index + by, 0, moved);
    void correct.run(() => reorderSession(session.id, order));
  };
  return (
    <section aria-labelledby="clips-heading">
      <h2 id="clips-heading">Clips in this session</h2>
      {correct.error && <p role="alert">{describeError(correct.error)}</p>}
      <ol className="clips">
        {session.assets.map((member, index) => {
          const name = media?.[member.asset_id]?.asset.original_name ?? member.asset_id;
          const segment = timeline.segments[index];
          const previous = ids[index - 1];
          const pair = previous ? overlapSource(overlaps, previous, member.asset_id) : undefined;
          const overlap = member.overlap_with_previous_ms ?? 0;
          const source = pair?.applied.source;
          return (
            <li key={member.asset_id} className="clip">
              <div className="clip-head">
                <strong>{name}</strong>
                <span className="muted">
                  {formatDuration(member.duration_ms)}
                  {media?.[member.asset_id] && !media[member.asset_id]?.url
                    ? " · cannot be played (original offline, no playback copy)"
                    : ""}
                </span>
              </div>
              {index > 0 && (
                <p className="muted">
                  {overlap > 0
                    ? `Starts with ${formatClock(overlap)} of footage the previous clip already shows${
                        source === "user"
                          ? " (set by you)."
                          : ` (found automatically${member.alignment_confidence !== undefined ? `, ${percent(member.alignment_confidence)} sure` : ""}).`
                      }`
                    : source === "user"
                      ? "You marked this clip as not repeating the previous one."
                      : "No repeated footage found with the previous clip."}
                </p>
              )}
              <div className="row">
                {segment && segment.virtualEndMs > segment.virtualStartMs && (
                  <button type="button" onClick={() => onSeek(segment.virtualStartMs)}>
                    Play from here
                  </button>
                )}
                <button
                  type="button"
                  disabled={index === 0 || correct.busy}
                  onClick={() => move(index, -1)}
                  aria-label={`Move ${name} earlier`}
                >
                  Move earlier
                </button>
                <button
                  type="button"
                  disabled={index === ids.length - 1 || correct.busy}
                  onClick={() => move(index, 1)}
                  aria-label={`Move ${name} later`}
                >
                  Move later
                </button>
                {index < ids.length - 1 && (
                  <button
                    type="button"
                    disabled={correct.busy}
                    onClick={() =>
                      void correct.run(() => splitSession(session.id, member.asset_id))
                    }
                    aria-label={`Start a new session after ${name}`}
                  >
                    Split after this clip
                  </button>
                )}
                {ids.length > 1 && (
                  <button
                    type="button"
                    disabled={correct.busy}
                    onClick={() =>
                      void correct.run(() => removeFromSession(session.id, member.asset_id))
                    }
                    aria-label={`${name} is not part of this session`}
                  >
                    Not part of this session
                  </button>
                )}
                {index > 0 && overlap > 0 && (
                  <button
                    type="button"
                    disabled={correct.busy}
                    onClick={() =>
                      void correct.run(() => setOverlap(session.id, member.asset_id, 0))
                    }
                    aria-label={`${name} does not repeat the previous clip`}
                  >
                    Not repeated footage
                  </button>
                )}
                {index > 0 && source === "user" && (
                  <button
                    type="button"
                    disabled={correct.busy}
                    onClick={() =>
                      void correct.run(() => setOverlap(session.id, member.asset_id, null))
                    }
                    aria-label={`Use the automatic match for ${name}`}
                  >
                    Use automatic match
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

const SKIP_MS = 5000;

/** One session as a continuous, gap-free timeline with corrections. */
export function SessionView({ id }: { id: string }) {
  const session = useQuery(`sessions:${id}`, () => getSession(id));
  const overlaps = useQuery(`sessions:${id}:overlaps`, () => sessionOverlaps(id));
  const ids = session.data?.assets.map((m) => m.asset_id) ?? [];
  const mediaKey = ids.length ? `session-media:${[...ids].sort().join(",")}` : null;
  const media = useQuery(mediaKey, () => loadMembers(ids));
  const confirm = useAction(async () => {
    await confirmSession(id);
    invalidate("sessions");
  });

  const [reveal, setReveal] = useState(false);
  const members = useMemo(
    () => (session.data ? timelineMembers(session.data, media.data) : null),
    [session.data, media.data],
  );
  const timeline = useMemo(
    () => (members ? buildTimeline(members, { reveal }) : null),
    [members, reveal],
  );

  const video0 = useRef<HTMLVideoElement>(null);
  const video1 = useRef<HTMLVideoElement>(null);
  const player = useRef<SessionPlayer | null>(null);
  const urls = useRef<Record<string, MemberMedia>>({});
  urls.current = media.data ?? {};
  const [state, setState] = useState<PlayerState | null>(null);
  const [waiting, setWaiting] = useState(false);

  const ready = Boolean(timeline && media.data);
  useEffect(() => {
    if (!timeline || !media.data || !video0.current || !video1.current) return;
    if (!player.current) {
      player.current = new SessionPlayer(
        timeline,
        [video0.current, video1.current],
        (assetId) => urls.current[assetId]?.url ?? "",
        setState,
      );
      setState(player.current.state);
    } else {
      player.current.setTimeline(timeline);
    }
  }, [timeline, media.data]);

  useEffect(() => () => player.current?.pause(), []);

  // Drive boundary switches once per frame while playing.
  const playing = state?.playing ?? false;
  useEffect(() => {
    if (!playing) return;
    let frame = requestAnimationFrame(function loop() {
      player.current?.tick();
      frame = requestAnimationFrame(loop);
    });
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const seek = useCallback((virtualMs: number) => player.current?.seek(virtualMs), []);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const p = player.current;
    if (!p || !timeline) return;
    const target = event.target as HTMLElement;
    const pressesControl =
      (target.tagName === "BUTTON" || (target as HTMLInputElement).type === "checkbox") &&
      (event.key === " " || event.key === "Enter");
    if (pressesControl || event.metaKey || event.ctrlKey || event.altKey) return;
    const now = p.virtualMs;
    const actions: Record<string, () => void> = {
      " ": () => p.toggle(),
      k: () => p.toggle(),
      ArrowLeft: () => p.seek(now - SKIP_MS),
      ArrowRight: () => p.seek(now + SKIP_MS),
      ",": () => p.step(-1),
      ".": () => p.step(1),
      Home: () => p.seek(0),
      End: () => p.seek(timeline.durationMs),
      "[": () => p.seek(nearestBoundary(timeline, now, -1)),
      "]": () => p.seek(nearestBoundary(timeline, now, 1)),
      r: () => setReveal((v) => !v),
      m: () => p.setMuted(!p.muted),
    };
    const action = actions[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  };

  if (session.error) {
    return (
      <section className="view">
        <a href={routeHref({ view: "sessions" })}>← Sessions</a>
        <div role="alert" className="notice-box">
          <p>This session could not be loaded: {describeError(session.error)}</p>
          <button type="button" onClick={session.refetch}>
            Try again
          </button>
        </div>
      </section>
    );
  }
  if (!session.data || !timeline) {
    return (
      <section className="view">
        <a href={routeHref({ view: "sessions" })}>← Sessions</a>
        <p role="status">Loading session…</p>
      </section>
    );
  }

  const data = session.data;
  const virtualMs = state?.virtualMs ?? 0;
  // The clip actually showing (at an exact boundary, the end of the clip just played).
  const shown = state ? timeline.segments[state.segmentIndex] : undefined;
  const position = shown
    ? { segment: shown, sourceMs: shown.sourceInMs + (virtualMs - shown.virtualStartMs) }
    : toSource(timeline, virtualMs);
  const current = position ? media.data?.[position.segment.assetId] : undefined;
  const active = state?.activeElement ?? 0;
  const repeated = repeatedMs(timeline);
  const frame = frameMs(position ? timeline.members[position.segment.index] : undefined);

  const videoProps = (index: 0 | 1) => ({
    className: index === active ? "session-video active" : "session-video",
    preload: "auto" as const,
    playsInline: true,
    "aria-hidden": index !== active,
    onEnded: () => player.current?.ended(index),
    // Animation frames pause in background windows; timeupdate keeps boundaries working.
    onTimeUpdate: () => {
      if (index === active) player.current?.tick();
    },
    onError: () => player.current?.failed(index, "This clip could not be played."),
    onWaiting: () => index === active && setWaiting(true),
    onPlaying: () => index === active && setWaiting(false),
    onSeeked: () => index === active && setWaiting(false),
  });

  return (
    <section className="view session" aria-labelledby="session-heading">
      <a href={routeHref({ view: "sessions" })}>← Sessions</a>
      <div className="view-head">
        <h1 id="session-heading">{data.title}</h1>
        <div className="row">
          <span className="badge">{STATE_TEXT[data.review_state]}</span>
          {data.review_state === "unreviewed" && (
            <button type="button" disabled={confirm.busy} onClick={() => void confirm.run()}>
              Confirm session
            </button>
          )}
        </div>
      </div>
      {confirm.error && <p role="alert">{describeError(confirm.error)}</p>}
      {media.error && (
        <p role="alert">Clip details could not be loaded: {describeError(media.error)}</p>
      )}

      <div
        className="session-player"
        role="group"
        aria-label="Session player"
        tabIndex={0}
        onKeyDown={onKeyDown}
      >
        <div className="session-screen">
          <video ref={video0} {...videoProps(0)} />
          <video ref={video1} {...videoProps(1)} />
          {!ready && (
            <div className="player-empty" role="status">
              Loading clips…
            </div>
          )}
          {ready && timeline.durationMs === 0 && (
            <div className="player-empty" role="status">
              Nothing in this session can be played.
            </div>
          )}
          {ready && waiting && playing && (
            <div className="player-loading" role="status">
              Loading…
            </div>
          )}
        </div>
        {state?.error && <p role="alert">{state.error} Playback stopped at this point.</p>}
        {ready && current && !current.url && (
          <p role="alert">
            {current.asset.original_name} cannot be played: the original is offline and has no
            playback copy.
          </p>
        )}

        <div className="transport">
          <button type="button" onClick={() => player.current?.toggle()} disabled={!ready}>
            {playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            onClick={() => player.current?.step(-1)}
            disabled={!ready}
            aria-label="Previous frame"
          >
            ◀︎ Frame
          </button>
          <button
            type="button"
            onClick={() => player.current?.step(1)}
            disabled={!ready}
            aria-label="Next frame"
          >
            Frame ▶︎
          </button>
          <button
            type="button"
            onClick={() => seek(nearestBoundary(timeline, virtualMs, -1))}
            disabled={!ready}
          >
            Previous clip
          </button>
          <button
            type="button"
            onClick={() => seek(nearestBoundary(timeline, virtualMs, 1))}
            disabled={!ready}
          >
            Next clip
          </button>
          <label className="check">
            <input
              type="checkbox"
              checked={state ? (player.current?.muted ?? false) : false}
              onChange={(e) => player.current?.setMuted(e.target.checked)}
              disabled={!ready}
            />
            Mute
          </label>
          <span className="clock" aria-live="off">
            {formatClock(virtualMs)} / {formatClock(timeline.durationMs)}
          </span>
        </div>
        <input
          className="scrub"
          type="range"
          min={0}
          max={timeline.durationMs}
          step={Math.max(1, Math.round(frame))}
          value={virtualMs}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label="Position in session"
          aria-valuetext={`${formatClock(virtualMs)} of ${formatClock(timeline.durationMs)}`}
          disabled={!ready}
        />
        <p className="muted source-time" aria-live="polite">
          {position && current
            ? `Clip ${position.segment.index + 1} of ${timeline.segments.length}: ${current.asset.original_name} at ${formatClock(position.sourceMs)}${current.usesProxy ? " (playback copy)" : ""}`
            : ""}
        </p>
        <Track timeline={timeline} media={media.data} virtualMs={virtualMs} onSeek={seek} />
        <label className="check">
          <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
          Show repeated footage
          {repeated > 0 ? ` (${formatClock(repeated)} ${reveal ? "shown" : "hidden"})` : ""}
        </label>
        <details className="shortcuts">
          <summary>Keyboard shortcuts</summary>
          <p>
            Space or K play/pause · ← → 5 seconds · , . one frame · [ ] previous/next clip ·
            Home/End start/end · R show repeated footage · M mute
          </p>
        </details>
      </div>

      <CreateProject sessionId={id} currentMs={virtualMs} />
      <ClipList
        session={data}
        media={media.data}
        overlaps={overlaps.data}
        timeline={timeline}
        onSeek={seek}
      />
      <EventReviewPanel sessionId={id} timeline={timeline} virtualMs={virtualMs} onSeek={seek} />
      <TranscriptPanel sessionId={id} onSeek={seek} />
    </section>
  );
}
