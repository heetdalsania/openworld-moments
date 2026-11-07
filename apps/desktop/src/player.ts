// SPDX-License-Identifier: AGPL-3.0-or-later
// Multi-clip playback over a virtual session timeline (M13).
//
// Two media elements take turns: the active one plays the current clip while the
// standby one is already loaded at the next clip's first unique frame. When the active
// clip reaches the end of its segment, playback switches to the standby element, so
// confirmed repeated footage is never replayed and the virtual clock never jumps.
// The controller talks to elements through `MediaLike`, so it is testable without a
// browser.
import {
  frameMs,
  indexOf,
  type Segment,
  stepFrame,
  type Timeline,
  toSource,
  toVirtual,
} from "./timeline";

export interface MediaLike {
  src: string;
  currentTime: number;
  paused: boolean;
  /** Only the visible element is ever audible, so audio follows the picture across switches. */
  muted: boolean;
  play(): Promise<void> | void;
  pause(): void;
}

export interface PlayerState {
  virtualMs: number;
  playing: boolean;
  /** Clip index on the timeline. */
  segmentIndex: number;
  /** Which of the two elements is visible. */
  activeElement: 0 | 1;
  error?: string;
}

/** Switch this many ms before a segment's end (half a frame), so the last frame shows once. */
function switchEarlyMs(timeline: Timeline, segment: Segment): number {
  return frameMs(timeline.members[segment.index]) / 2;
}

export class SessionPlayer {
  private active: 0 | 1 = 0;
  private segment: Segment | null = null;
  private playing = false;
  private error: string | undefined;
  private standbySegment: Segment | null = null;
  private userMuted = false;

  constructor(
    private timeline: Timeline,
    private readonly elements: readonly [MediaLike, MediaLike],
    private readonly urlFor: (assetId: string) => string,
    private readonly onChange: (state: PlayerState) => void = () => undefined,
  ) {
    this.seek(0);
  }

  get state(): PlayerState {
    return {
      virtualMs: this.virtualMs,
      playing: this.playing,
      segmentIndex: this.segment?.index ?? 0,
      activeElement: this.active,
      ...(this.error ? { error: this.error } : {}),
    };
  }

  /** The virtual clock, derived from the active element's position. */
  get virtualMs(): number {
    const segment = this.segment;
    if (!segment) return 0;
    const sourceMs = this.elements[this.active].currentTime * 1000;
    const offset = Math.min(
      Math.max(0, sourceMs - segment.sourceInMs),
      segment.virtualEndMs - segment.virtualStartMs,
    );
    return Math.round(segment.virtualStartMs + offset);
  }

  private emit(): void {
    this.onChange(this.state);
  }

  /** The active element carries both picture and sound; the standby one stays silent. */
  private syncAudio(): void {
    this.elements[this.active].muted = this.userMuted;
    this.elements[this.active === 0 ? 1 : 0].muted = true;
  }

  get muted(): boolean {
    return this.userMuted;
  }

  setMuted(muted: boolean): void {
    this.userMuted = muted;
    this.syncAudio();
    this.emit();
  }

  private load(element: MediaLike, segment: Segment, sourceMs: number): void {
    const url = this.urlFor(segment.assetId);
    if (element.src !== url) element.src = url;
    element.currentTime = sourceMs / 1000;
  }

  private nextPlayable(after: Segment): Segment | null {
    return (
      this.timeline.segments.find(
        (s) => s.index > after.index && s.virtualEndMs > s.virtualStartMs,
      ) ?? null
    );
  }

  private preloadNext(): void {
    const next = this.segment ? this.nextPlayable(this.segment) : null;
    this.standbySegment = next;
    if (next) this.load(this.elements[this.active === 0 ? 1 : 0], next, next.sourceInMs);
  }

  /** Jump to virtual time `virtualMs` (keeps playing or paused). */
  seek(virtualMs: number): void {
    const position = toSource(this.timeline, virtualMs);
    if (!position) {
      this.segment = null;
      this.emit();
      return;
    }
    this.place(position.segment, position.sourceMs);
  }

  /** Show `segment` at `sourceMs` (keeps playing or paused). */
  private place(segment: Segment, sourceMs: number): void {
    const element = this.elements[this.active];
    element.pause();
    this.segment = segment;
    this.load(element, segment, sourceMs);
    this.preloadNext();
    this.syncAudio();
    if (this.playing) void this.resume(element);
    this.emit();
  }

  private async resume(element: MediaLike): Promise<void> {
    try {
      this.error = undefined;
      await element.play();
    } catch (error) {
      this.playing = false;
      this.error = error instanceof Error ? error.message : String(error);
      this.emit();
    }
  }

  play(): void {
    if (!this.segment) return;
    if (this.virtualMs >= this.timeline.durationMs) this.seek(0);
    this.playing = true;
    void this.resume(this.elements[this.active]);
    this.emit();
  }

  pause(): void {
    this.playing = false;
    this.elements[this.active].pause();
    this.emit();
  }

  toggle(): void {
    if (this.playing) this.pause();
    else this.play();
  }

  /** Step one frame of the visible clip, pausing playback. */
  step(direction: 1 | -1): void {
    this.pause();
    this.seek(stepFrame(this.timeline, this.virtualMs, direction));
  }

  /** Call on every animation frame / timeupdate while playing: switches clips at boundaries. */
  tick(): void {
    const segment = this.segment;
    if (!segment) return;
    const sourceMs = this.elements[this.active].currentTime * 1000;
    if (sourceMs >= segment.sourceOutMs - switchEarlyMs(this.timeline, segment)) {
      this.advance();
    }
    this.emit();
  }

  /**
   * The element reached its media end (a playback copy can be a frame shorter than the
   * metadata duration, so `tick` alone might never see the segment end).
   */
  ended(element: 0 | 1): void {
    if (element !== this.active || !this.segment) return;
    this.advance();
    this.emit();
  }

  /** The element could not load or decode its clip: stop and report, keep the position. */
  failed(element: 0 | 1, message: string): void {
    if (element !== this.active) return;
    this.playing = false;
    this.error = message;
    this.elements[this.active].pause();
    this.emit();
  }

  private advance(): void {
    const current = this.segment;
    if (!current) return;
    const next = this.nextPlayable(current);
    const outgoing = this.elements[this.active];
    if (!next) {
      outgoing.pause();
      outgoing.currentTime = current.sourceOutMs / 1000;
      this.playing = false;
      return;
    }
    outgoing.pause();
    this.active = this.active === 0 ? 1 : 0;
    const incoming = this.elements[this.active];
    if (this.standbySegment !== next) this.load(incoming, next, next.sourceInMs);
    else incoming.currentTime = next.sourceInMs / 1000;
    this.segment = next;
    this.preloadNext();
    this.syncAudio();
    if (this.playing) void this.resume(incoming);
  }

  /**
   * Use a new timeline (duplicates revealed or hidden, clips reordered) and stay on the
   * same moment of the same clip where possible.
   */
  setTimeline(timeline: Timeline): void {
    const segment = this.segment;
    const sourceMs = this.elements[this.active].currentTime * 1000;
    this.timeline = timeline;
    const index = segment ? indexOf(timeline, segment.assetId) : -1;
    const same = timeline.segments[index];
    if (
      same &&
      same.virtualEndMs > same.virtualStartMs &&
      sourceMs >= same.sourceInMs &&
      sourceMs <= same.sourceOutMs
    ) {
      // Still visible in the same clip: stay on it, even at its very end.
      this.place(same, sourceMs);
      return;
    }
    // Now hidden (or the clip left the session): the same moment elsewhere, else the start.
    this.seek(index >= 0 ? (toVirtual(timeline, index, sourceMs)?.virtualMs ?? 0) : 0);
  }
}
