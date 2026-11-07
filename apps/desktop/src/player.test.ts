// SPDX-License-Identifier: AGPL-3.0-or-later
// Playback controller across clip boundaries (M13), with fake media elements that
// advance their clock like a playing <video>.
import { describe, expect, it } from "vitest";
import { type MediaLike, SessionPlayer } from "./player";
import { buildTimeline, type TimelineMember } from "./timeline";

class FakeMedia implements MediaLike {
  src = "";
  currentTime = 0;
  paused = true;
  muted = false;
  plays = 0;
  failNextPlay = false;
  /** Every (src, time) a frame was shown at while playing, for replay checks. */
  shown: [string, number][] = [];

  play(): Promise<void> {
    if (this.failNextPlay) {
      this.failNextPlay = false;
      return Promise.reject(new Error("decode error"));
    }
    this.paused = false;
    this.plays++;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }

  advance(ms: number): void {
    if (this.paused) return;
    this.currentTime += ms / 1000;
    this.shown.push([this.src, Math.round(this.currentTime * 1000)]);
  }
}

const A = "ast_01JCBQ00000000000000000001";
const B = "ast_01JCBQ00000000000000000002";
const C = "ast_01JCBQ00000000000000000003";
const url = (id: string) => `owm-media://localhost/asset/${id}/proxy`;

function setup(members: TimelineMember[], reveal = false) {
  const elements: [FakeMedia, FakeMedia] = [new FakeMedia(), new FakeMedia()];
  const timeline = buildTimeline(members, { reveal });
  const player = new SessionPlayer(timeline, elements, url);
  return { elements, player, timeline };
}

/** Run playback for `ms` in 20 ms steps, as animation frames would. */
async function run(player: SessionPlayer, elements: FakeMedia[], ms: number) {
  for (let t = 0; t < ms; t += 20) {
    for (const e of elements) e.advance(20);
    player.tick();
    await Promise.resolve();
  }
}

const members: TimelineMember[] = [
  { assetId: A, durationMs: 2000, overlapMs: 0, frameRate: { num: 50, den: 1 } },
  { assetId: B, durationMs: 2000, overlapMs: 600, frameRate: { num: 50, den: 1 } },
  { assetId: C, durationMs: 1000, overlapMs: 0, frameRate: { num: 50, den: 1 } },
];

describe("session playback", () => {
  it("starts on the first clip with the next one preloaded at its first unique frame", () => {
    const { elements, player } = setup(members);
    expect(elements[0].src).toBe(url(A));
    expect(elements[1].src).toBe(url(B));
    expect(elements[1].currentTime).toBeCloseTo(0.6);
    expect(player.state).toMatchObject({ virtualMs: 0, playing: false, segmentIndex: 0 });
  });

  it("crosses a boundary without replaying the hidden overlap and keeps the clock", async () => {
    const { elements, player } = setup(members);
    player.play();
    await run(player, elements, 2100);
    // Now on B, which started at its 600 ms mark: A's repeated end is not replayed.
    expect(player.state.segmentIndex).toBe(1);
    expect(player.state.activeElement).toBe(1);
    const bFrames = elements[1].shown.filter(([src]) => src === url(B)).map(([, t]) => t);
    expect(Math.min(...bFrames)).toBeGreaterThanOrEqual(600);
    expect(elements[0].paused).toBe(true);
    // The virtual clock kept running across the switch (A 2000 ms + time in B).
    expect(player.virtualMs).toBeGreaterThanOrEqual(2000);
    expect(player.virtualMs).toBeLessThan(2200);
    // The element that played A now waits at C's start.
    expect(elements[0].src).toBe(url(C));
    expect(elements[0].currentTime).toBe(0);
  });

  it("keeps sound with the picture: only the visible clip is audible (A/V boundary smoke)", async () => {
    const { elements, player } = setup(members);
    expect([elements[0].muted, elements[1].muted]).toEqual([false, true]);
    player.play();
    await run(player, elements, 2100);
    // After the switch to B, its element is audible and A's (now preloading C) is silent,
    // and no element played while muted-out of view.
    expect([elements[0].muted, elements[1].muted]).toEqual([true, false]);
    expect(elements[0].paused).toBe(true);
    player.setMuted(true);
    expect(elements.every((e) => e.muted)).toBe(true);
    player.seek(0);
    expect(elements.every((e) => e.muted)).toBe(true);
    player.setMuted(false);
    expect(elements[player.state.activeElement].muted).toBe(false);
  });

  it("plays to the end and stops", async () => {
    const { elements, player, timeline } = setup(members);
    player.play();
    await run(player, elements, 5000);
    expect(player.state.playing).toBe(false);
    expect(player.state.segmentIndex).toBe(2);
    expect(player.virtualMs).toBe(timeline.durationMs);
    player.play(); // playing again from the end restarts
    expect(player.state.segmentIndex).toBe(0);
  });

  it("seeks to the right clip and source time", () => {
    const { elements, player } = setup(members);
    player.seek(2500); // B's segment starts at virtual 2000, source 600
    expect(player.state.segmentIndex).toBe(1);
    expect(elements[player.state.activeElement].src).toBe(url(B));
    expect(elements[player.state.activeElement].currentTime).toBeCloseTo(1.1);
    expect(player.virtualMs).toBe(2500);
    player.seek(3400); // C starts at 2000 + 1400
    expect(player.state.segmentIndex).toBe(2);
    expect(elements[player.state.activeElement].currentTime).toBe(0);
  });

  it("steps frames across a boundary and pauses", () => {
    const { player } = setup(members);
    player.seek(1980); // A's last frame at 50 fps
    player.play();
    player.step(1);
    expect(player.state).toMatchObject({ playing: false, segmentIndex: 1, virtualMs: 2000 });
    player.step(-1);
    expect(player.state).toMatchObject({ segmentIndex: 0, virtualMs: 1980 });
  });

  it("revealing duplicates keeps the same moment and plays the repeated range", async () => {
    const { elements, player } = setup(members);
    player.seek(2500); // B at 1100 ms
    player.setTimeline(buildTimeline(members, { reveal: true }));
    expect(player.state.segmentIndex).toBe(1);
    expect(elements[player.state.activeElement].currentTime).toBeCloseTo(1.1);
    expect(player.virtualMs).toBe(3100); // A 2000 + B 1100 (nothing hidden now)
    player.seek(1900);
    player.play();
    await run(player, elements, 300);
    const shownB = elements.flatMap((e) => e.shown).filter(([src]) => src === url(B));
    expect(Math.min(...shownB.map(([, t]) => t))).toBeLessThan(600); // the duplicate plays
  });

  it("reordering keeps the playing clip and moment", () => {
    const { player } = setup(members);
    player.seek(3600); // C at 200 ms
    const reordered = buildTimeline([
      members[2],
      members[0],
      { ...members[1], overlapMs: 0 },
    ] as TimelineMember[]);
    player.setTimeline(reordered);
    expect(player.state.segmentIndex).toBe(0); // C is first now
    expect(player.virtualMs).toBe(200);
  });

  it("a new layout at the very end of a clip stays on that clip", () => {
    const { elements, player } = setup(members);
    player.seek(3000); // in B
    elements[player.state.activeElement].currentTime = 2.0; // B's last moment
    player.setTimeline(buildTimeline(members));
    // Virtual 3400 is also C's start; the visible clip is still B.
    expect(player.state).toMatchObject({ segmentIndex: 1, virtualMs: 3400 });
    expect(elements[player.state.activeElement].src).toBe(url(B));
  });

  it("reports a playback error and stops", async () => {
    const { elements, player } = setup(members);
    elements[0].failNextPlay = true;
    const states: string[] = [];
    const watched = new SessionPlayer(buildTimeline(members), elements, url, (s) => {
      if (s.error) states.push(s.error);
    });
    watched.play();
    await Promise.resolve();
    await Promise.resolve();
    expect(states).toContain("decode error");
    expect(watched.state.playing).toBe(false);
    void player;
  });

  it("moves on when a playback copy ends a little before the metadata duration", () => {
    const { elements, player } = setup(members);
    player.play();
    elements[0].currentTime = 1.95; // stalled 50 ms short of A's 2000 ms
    player.tick();
    expect(player.state.segmentIndex).toBe(0);
    player.ended(1); // the standby element's end is ignored
    expect(player.state.segmentIndex).toBe(0);
    player.ended(0);
    expect(player.state).toMatchObject({ segmentIndex: 1, playing: true, virtualMs: 2000 });
  });

  it("stops with a message when the visible clip cannot be loaded", () => {
    const { player } = setup(members);
    player.play();
    player.failed(1, "ignored: standby");
    expect(player.state.error).toBeUndefined();
    player.failed(0, "This clip could not be played.");
    expect(player.state).toMatchObject({ playing: false, error: "This clip could not be played." });
  });

  it("handles an empty session", () => {
    const { player } = setup([]);
    player.play();
    expect(player.state).toMatchObject({ playing: false, virtualMs: 0 });
  });
});
