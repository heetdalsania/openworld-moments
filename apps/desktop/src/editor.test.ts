// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { load, type EditorProject } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { applyCommand, EditorHistory, type EditorCommand } from "./editor";

const document = (): EditorProject => structuredClone(load("editor-project", fixture));
const sid = (n: number): string => `seg_${String(n).padStart(26, "0")}`;
function segments(d: EditorProject) {
  const track = d.project.tracks[0];
  if (!track) throw new Error("Missing test track");
  return track.segments;
}
function segment(d: EditorProject, index = 0) {
  const value = segments(d)[index];
  if (!value) throw new Error("Missing test segment");
  return value;
}
const first = (): string => segment(document()).id;

describe("editor commands", () => {
  it("round trips add, trim, split, delete, reorder, settings without mutating callers", () => {
    const initial = document(),
      h = new EditorHistory(initial);
    const commands: EditorCommand[] = [
      {
        kind: "add",
        index: 1,
        segment: { ...structuredClone(segment(initial, 1)), id: sid(1) },
      },
      { kind: "trim", id: first(), source_in_ms: 13000, source_out_ms: 44000 },
      { kind: "split", id: first(), at_ms: 1000, new_id: sid(2) },
      { kind: "delete", id: sid(1) },
      { kind: "reorder", ids: [sid(2), first(), segment(initial, 1).id] },
      { kind: "settings", title: "Edited", layout: { aspect_ratio: "9:16" } },
    ];
    for (const command of commands) {
      const before = h.document,
        after = h.execute(command);
      expect(h.undo()).toEqual(before);
      expect(h.redo()).toEqual(after);
      expect(load("editor-project", after)).toEqual(after);
    }
    for (let i = 0; i < commands.length; i++) h.undo();
    expect(h.document).toEqual(initial);
    expect(initial).toEqual(document());
  });
  it("retimes captions, blur/text, gain and mute through split, reorder and deletion", () => {
    const d = document();
    d.project.captions = [{ start_ms: 100, end_ms: 1100, text: "Keep" }];
    d.project.audio.mute_ranges = [{ start_ms: 100, end_ms: 1100 }];
    const split = applyCommand(d, { kind: "split", id: first(), at_ms: 500, new_id: sid(9) });
    expect(split.project.captions.map((x) => [x.start_ms, x.end_ms])).toEqual([
      [100, 500],
      [500, 1100],
    ]);
    const reorder = applyCommand(split, {
      kind: "reorder",
      ids: [segment(d, 1).id, first(), sid(9)],
    });
    expect(reorder.project.captions.map((x) => x.start_ms)).toEqual([11100, 11500]);
    expect(reorder.project.audio.gain_ranges?.[0]?.start_ms).toBe(11000);
    expect(reorder.project.overlays[0]?.start_ms).toBe(11000);
    expect(reorder.project.audio.mute_ranges[0]?.start_ms).toBe(11100);
    const deleted = applyCommand(reorder, { kind: "delete", id: first() });
    expect(deleted.project.captions[0]).toMatchObject({ start_ms: 11000, end_ms: 11600 });
  });
  it("carries the active manual crop into a split and trim", () => {
    const d = document(),
      s = segment(d, 0);
    s.crop = {
      mode: "manual",
      keyframes: [
        { at_ms: 0, region: [0, 0, 0.5, 1] },
        { at_ms: 1000, region: [0.5, 0, 0.5, 1] },
      ],
    };
    const split = applyCommand(d, { kind: "split", id: s.id, at_ms: 1500, new_id: sid(2) });
    expect(segment(split, 1).crop.keyframes).toEqual([{ at_ms: 0, region: [0.5, 0, 0.5, 1] }]);
    const trimmed = applyCommand(d, {
      kind: "trim",
      id: s.id,
      source_in_ms: 14000,
      source_out_ms: 15000,
    });
    expect(segment(trimmed, 0).crop.keyframes[0]?.region).toEqual([0.5, 0, 0.5, 1]);
  });
  it("rejects invalid commands atomically and keeps redo on failure", () => {
    const h = new EditorHistory(document());
    h.execute({ kind: "delete", id: first() });
    h.undo();
    const initial = h.document;
    const invalid: EditorCommand[] = [
      { kind: "trim", id: first(), source_in_ms: -1, source_out_ms: 30 },
      { kind: "trim", id: first(), source_in_ms: 0, source_out_ms: 120001 },
      { kind: "trim", id: first(), source_in_ms: 30, source_out_ms: 30 },
      { kind: "split", id: first(), at_ms: 0, new_id: sid(2) },
      { kind: "split", id: first(), at_ms: 32300, new_id: sid(2) },
      { kind: "split", id: first(), at_ms: 1.5, new_id: sid(2) },
      { kind: "split", id: first(), at_ms: 100, new_id: first() },
      { kind: "delete", id: "unknown" },
      { kind: "reorder", ids: [first(), first()] },
      { kind: "settings", captions: [{ start_ms: 0, end_ms: 999999, text: "outside" }] },
      { kind: "add", index: -1, segment: segment(initial, 0) },
    ];
    for (const command of invalid) {
      expect(() => h.execute(command)).toThrow();
      expect(h.document).toEqual(initial);
      expect(h.canRedo).toBe(true);
    }
  });
  it("bounds history, clears redo on a new command, and returns detached copies", () => {
    const h = new EditorHistory(document(), 2);
    for (const title of ["1", "2", "3"]) h.execute({ kind: "settings", title });
    h.undo();
    h.undo();
    h.undo();
    expect(h.document.project.title).toBe("1");
    h.execute({ kind: "settings", title: "new" });
    expect(h.canRedo).toBe(false);
    const detached = h.document;
    detached.project.title = "mutated";
    expect(h.document.project.title).toBe("new");
  });
  it("bounds serialized snapshot retention while keeping the latest operation reversible", () => {
    const d = document();
    d.project.captions = Array.from({ length: 2000 }, () => ({
      start_ms: 0,
      end_ms: 1,
      text: "x".repeat(1000),
    }));
    const h = new EditorHistory(d);
    for (let i = 0; i < 10; i++) h.execute({ kind: "settings", title: String(i) });
    expect(h.undo().project.title).toBe("8");
    for (let i = 0; i < 20; i++) h.undo();
    expect(Number(h.document.project.title)).toBeGreaterThan(0);
  });
  it("property: bounded command sequences remain valid and exactly reversible", () => {
    fc.assert(
      fc.property(
        fc.array(fc.tuple(fc.integer({ min: 0, max: 4 }), fc.nat(100000)), { maxLength: 60 }),
        (steps) => {
          const initial = document(),
            h = new EditorHistory(initial, 100);
          let id = 100,
            count = 0;
          for (const [kind, value] of steps) {
            const segs = segments(h.document);
            const s = segs[value % Math.max(1, segs.length)];
            let cmd: EditorCommand;
            if (!s || kind === 0) {
              const template = segment(initial, 1);
              cmd = {
                kind: "add",
                index: value % (segs.length + 1),
                segment: { ...structuredClone(template), id: sid(id++) },
              };
            } else if (kind === 1) {
              const a = value % 119999;
              cmd = {
                kind: "trim",
                id: s.id,
                source_in_ms: a,
                source_out_ms: a + 1 + (value % (120000 - a)),
              };
            } else if (kind === 2 && s.source_out_ms - s.source_in_ms > 1) {
              cmd = {
                kind: "split",
                id: s.id,
                at_ms: 1 + (value % (s.source_out_ms - s.source_in_ms - 1)),
                new_id: sid(id++),
              };
            } else if (kind === 3) cmd = { kind: "delete", id: s.id };
            else cmd = { kind: "reorder", ids: segs.map((x) => x.id).reverse() };
            const before = h.document,
              after = h.execute(cmd);
            count++;
            expect(load("editor-project", after)).toEqual(after);
            expect(h.undo()).toEqual(before);
            expect(h.redo()).toEqual(after);
          }
          for (let i = 0; i < count; i++) h.undo();
          expect(h.document).toEqual(initial);
        },
      ),
      { seed: 0x21, numRuns: 150 },
    );
  }, 30_000);
});
