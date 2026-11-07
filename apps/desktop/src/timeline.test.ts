// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import {
  boundaries,
  buildTimeline,
  frameMs,
  indexOf,
  nearestBoundary,
  repeatedMs,
  stepFrame,
  type TimelineMember,
  toSource,
  toVirtual,
} from "./timeline";

const A = "ast_01JCBQ00000000000000000001";
const B = "ast_01JCBQ00000000000000000002";
const C = "ast_01JCBQ00000000000000000003";

function member(assetId: string, durationMs: number, overlapMs = 0, fps = 60): TimelineMember {
  return { assetId, durationMs, overlapMs, frameRate: { num: fps, den: 1 } };
}

describe("building the timeline", () => {
  it("zero overlap: clips play end to end", () => {
    const t = buildTimeline([member(A, 40_000), member(B, 30_000)]);
    expect(t.durationMs).toBe(70_000);
    expect(t.segments.map((s) => [s.sourceInMs, s.virtualStartMs, s.virtualEndMs])).toEqual([
      [0, 0, 40_000],
      [0, 40_000, 70_000],
    ]);
    expect(repeatedMs(t)).toBe(0);
  });

  it("partial overlap: the repeated start of B is hidden", () => {
    const t = buildTimeline([member(A, 40_000), member(B, 40_000, 10_000)]);
    expect(t.durationMs).toBe(70_000);
    const b = t.segments[1];
    expect(b?.sourceInMs).toBe(10_000);
    expect(b?.hiddenMs).toBe(10_000);
    expect(b?.virtualStartMs).toBe(40_000);
    expect(repeatedMs(t)).toBe(10_000);
  });

  it("full overlap: a clip entirely repeated adds no virtual time", () => {
    const t = buildTimeline([member(A, 40_000), member(B, 8000, 8000), member(C, 20_000)]);
    expect(t.durationMs).toBe(60_000);
    expect(t.segments[1]?.virtualStartMs).toBe(t.segments[1]?.virtualEndMs);
    expect(toSource(t, 40_000)?.segment.assetId).toBe(C); // B is skipped
    expect(boundaries(t)).toEqual([40_000]);
  });

  it("overlaps are clamped to the clip and ignored on the first clip", () => {
    const t = buildTimeline([member(A, 10_000, 5000), member(B, 4000, 9000)]);
    expect(t.segments[0]?.hiddenMs).toBe(0);
    expect(t.segments[1]?.hiddenMs).toBe(4000);
    expect(t.durationMs).toBe(10_000);
  });

  it("revealing duplicates plays everything and marks the repeated range", () => {
    const t = buildTimeline([member(A, 40_000), member(B, 40_000, 10_000)], { reveal: true });
    expect(t.durationMs).toBe(80_000);
    const b = t.segments[1];
    expect([b?.sourceInMs, b?.hiddenMs, b?.revealedDuplicateMs]).toEqual([0, 0, 10_000]);
    expect(repeatedMs(t)).toBe(10_000);
  });

  it("an empty session has an empty timeline", () => {
    const t = buildTimeline([]);
    expect(t.durationMs).toBe(0);
    expect(toSource(t, 0)).toBeNull();
    expect(stepFrame(t, 0, 1)).toBe(0);
  });
});

describe("mapping virtual and source time", () => {
  const t = buildTimeline([member(A, 40_000), member(B, 40_000, 10_000), member(C, 20_000, 2500)]);

  it("selects the right clip, with boundaries belonging to the next clip", () => {
    expect(toSource(t, 0)).toMatchObject({ segment: { assetId: A }, sourceMs: 0 });
    expect(toSource(t, 39_999)).toMatchObject({ segment: { assetId: A }, sourceMs: 39_999 });
    expect(toSource(t, 40_000)).toMatchObject({ segment: { assetId: B }, sourceMs: 10_000 });
    expect(toSource(t, 70_000)).toMatchObject({ segment: { assetId: C }, sourceMs: 2500 });
    expect(toSource(t, t.durationMs)).toMatchObject({ segment: { assetId: C }, sourceMs: 20_000 });
    expect(toSource(t, -5)?.sourceMs).toBe(0); // clamped
    expect(toSource(t, 10 ** 9)?.sourceMs).toBe(20_000);
  });

  it("maps visible source time back exactly", () => {
    expect(toVirtual(t, 1, 10_000)).toEqual({ virtualMs: 40_000, exact: true });
    expect(toVirtual(t, 2, 20_000)).toEqual({ virtualMs: t.durationMs, exact: true });
    expect(toVirtual(t, 1, -1)).toBeNull();
    expect(toVirtual(t, 1, 40_001)).toBeNull();
    expect(toVirtual(t, 9, 0)).toBeNull();
  });

  it("maps hidden repeated footage to the same moment in the earlier clip", () => {
    // B's 2 s mark is A's 32 s mark (B starts 30 s into A).
    expect(toVirtual(t, 1, 2000)).toEqual({ virtualMs: 32_000, exact: false });
    // C's first 2.5 s repeat the end of B, which is visible.
    const cAtZero = toVirtual(t, 2, 0);
    expect(cAtZero?.exact).toBe(false);
    expect(toSource(t, cAtZero?.virtualMs ?? -1)).toMatchObject({
      segment: { assetId: B },
      sourceMs: 37_500,
    });
  });

  it("finds clips by asset ID", () => {
    expect(indexOf(t, C)).toBe(2);
    expect(indexOf(t, "ast_missing")).toBe(-1);
  });

  it.each([
    ["23.976", { num: 24000, den: 1001 }],
    ["24", { num: 24, den: 1 }],
    ["25", { num: 25, den: 1 }],
    ["29.97", { num: 30000, den: 1001 }],
    ["30", { num: 30, den: 1 }],
    ["50", { num: 50, den: 1 }],
    ["59.94", { num: 60000, den: 1001 }],
    ["60", { num: 60, den: 1 }],
    ["120", { num: 120, den: 1 }],
    ["VFR average 47.3", { num: 473, den: 10 }],
  ])("round trips every frame within one frame at %s fps", (_, frameRate) => {
    const timeline = buildTimeline([
      { assetId: A, durationMs: 9_876, overlapMs: 0, frameRate },
      { assetId: B, durationMs: 7_531, overlapMs: 1_234, frameRate },
      { assetId: C, durationMs: 5_000, overlapMs: 5_000, frameRate },
    ]);
    const frame = (1000 * frameRate.den) / frameRate.num;
    for (const segment of timeline.segments) {
      for (let k = 0; segment.sourceInMs + k * frame < segment.sourceOutMs; k++) {
        const source = segment.sourceInMs + k * frame;
        const virtual = toVirtual(timeline, segment.index, source);
        expect(virtual?.exact).toBe(true);
        const back = toSource(timeline, virtual?.virtualMs ?? -1);
        expect(back?.segment.index).toBe(segment.index);
        expect(Math.abs((back?.sourceMs ?? 0) - source)).toBeLessThan(frame);
      }
    }
    for (let v = 0; v <= timeline.durationMs; v += 97) {
      const source = toSource(timeline, v);
      if (!source) throw new Error("expected a source");
      expect(toVirtual(timeline, source.segment.index, source.sourceMs)?.virtualMs).toBe(v);
    }
  });
});

describe("frame stepping and boundaries", () => {
  const t = buildTimeline([member(A, 1000, 0, 25), member(B, 1000, 400, 50)]);

  it("steps by the playing clip's frame", () => {
    expect(frameMs(t.members[0])).toBe(40);
    expect(stepFrame(t, 0, 1)).toBe(40);
    expect(stepFrame(t, 1000, 1)).toBe(1020); // in B, 50 fps
    expect(stepFrame(t, 1020, -1)).toBe(1000);
  });

  it("crosses boundaries onto unique frames", () => {
    expect(stepFrame(t, 980, 1)).toBe(1000); // A's last frame -> B's first unique frame
    expect(stepFrame(t, 1000, -1)).toBe(960); // B's first unique frame -> A's last frame
    expect(stepFrame(t, 0, -1)).toBe(0);
    expect(stepFrame(t, t.durationMs - 1, 1)).toBe(t.durationMs);
  });

  it("uses the average rate for VFR and 30 fps when unknown", () => {
    expect(
      frameMs({ assetId: A, durationMs: 1, overlapMs: 0, frameRate: { num: 473, den: 10 } }),
    ).toBeCloseTo(21.14, 2);
    expect(frameMs({ assetId: A, durationMs: 1, overlapMs: 0 })).toBeCloseTo(33.33, 2);
  });

  it("navigates between clip boundaries", () => {
    expect(boundaries(t)).toEqual([1000]);
    expect(nearestBoundary(t, 300, 1)).toBe(1000);
    expect(nearestBoundary(t, 1000, 1)).toBe(t.durationMs);
    expect(nearestBoundary(t, 1300, -1)).toBe(1000);
    expect(nearestBoundary(t, 1000, -1)).toBe(0);
  });
});
