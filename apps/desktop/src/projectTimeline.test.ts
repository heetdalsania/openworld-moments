// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, it } from "vitest";
import { load } from "@openworld-moments/contracts";
import sessionFixture from "../../../packages/contracts/fixtures/session/valid/automatic.json";
import reviewFixture from "../../../packages/contracts/fixtures/event-review/valid/observation.json";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { applyCommand } from "./editor";
import { SessionPlayer, type MediaLike } from "./player";
import { projectTimeline, projectMarkers } from "./projectTimeline";
import { toSource } from "./timeline";

function element(): MediaLike {
  return {
    src: "",
    currentTime: 0,
    paused: true,
    muted: true,
    play() {
      this.paused = false;
    },
    pause() {
      this.paused = true;
    },
  };
}
it("maps source ranges and every exact boundary without confusing repeated source assets", () => {
  const d = structuredClone(load("editor-project", fixture)),
    t = projectTimeline(d);
  expect(toSource(t, 32300)).toMatchObject({ sourceMs: 50000, segment: { index: 1 } });
  const first = t.segments[0];
  if (!first) throw new Error("fixture");
  expect(toSource(t, 0)?.sourceMs).toBe(12500);
  expect(toSource(t, t.durationMs)?.sourceMs).toBe(61000);
  expect(t.segments.map((s) => s.assetId)).toEqual([first.assetId, first.assetId]);
});
it("keeps the same cut/source moment on reorder, trim, undo and redo within one source frame", () => {
  const d = structuredClone(load("editor-project", fixture));
  const a = element(),
    b = element();
  const p = new SessionPlayer(projectTimeline(d), [a, b], (id) => id);
  p.seek(35000);
  expect(p.state.segmentIndex).toBe(1);
  const ids = (d.project.tracks[0]?.segments ?? []).map((s) => s.id).reverse();
  const reordered = applyCommand(d, { kind: "reorder", ids });
  p.setTimeline(projectTimeline(reordered));
  expect(p.state.segmentIndex).toBe(0);
  expect(p.virtualMs).toBe(2700);
  expect(a.currentTime).toBe(52.7);
  p.setTimeline(projectTimeline(d));
  expect(p.state.segmentIndex).toBe(1);
  expect(p.virtualMs).toBe(35000);
  p.setTimeline(projectTimeline(reordered));
  expect(p.virtualMs).toBe(2700);
  const id = ids[0];
  if (!id) throw new Error("fixture");
  const trimmed = applyCommand(reordered, {
    kind: "trim",
    id,
    source_in_ms: 52000,
    source_out_ms: 60000,
  });
  p.setTimeline(projectTimeline(trimmed));
  expect(p.virtualMs).toBe(700);
  expect(a.currentTime).toBe(52.7);
});
it("steps and switches at a trimmed boundary within half a frame, then ends without replaying removed footage", () => {
  const d = structuredClone(load("editor-project", fixture));
  const a = element(),
    b = element();
  const p = new SessionPlayer(
    projectTimeline(d, { [d.sources[0]?.asset_id ?? ""]: { num: 60, den: 1 } }),
    [a, b],
    (id) => id,
  );
  p.seek(32290);
  p.step(1);
  expect(p.virtualMs).toBe(32300);
  expect(a.currentTime).toBe(50);
  p.seek(32290);
  p.play();
  a.currentTime = 44.795;
  p.tick();
  expect(p.state.segmentIndex).toBe(1);
  expect(p.virtualMs).toBe(32300);
  expect(b.currentTime).toBe(50);
  b.currentTime = 61;
  p.tick();
  expect(p.state.playing).toBe(false);
  expect(p.virtualMs).toBe(43300);
});

it("clamps a trimmed-away source moment to the same cut instead of inventing a session overlap", () => {
  const d = structuredClone(load("editor-project", fixture));
  const cut = d.project.tracks[0]?.segments[1];
  if (!cut) throw new Error("fixture");
  const a = element(),
    b = element();
  const p = new SessionPlayer(projectTimeline(d), [a, b], (id) => id);
  p.seek(33000);
  const trim = applyCommand(d, {
    kind: "trim",
    id: cut.id,
    source_in_ms: 54000,
    source_out_ms: 61000,
  });
  p.setTimeline(projectTimeline(trim));
  expect(p.state.segmentIndex).toBe(1);
  expect(p.virtualMs).toBe(32300);
  expect(a.currentTime).toBe(54);
});

it("maps only current same-session event context through retained source ranges", () => {
  const d = structuredClone(load("editor-project", fixture));
  const aid = d.sources[0]?.asset_id ?? "",
    sid = d.project.session_id ?? "";
  const session = load("session", {
    ...sessionFixture,
    id: sid,
    assets: [{ asset_id: aid, duration_ms: 120000, order_index: 0, session_start_ms: 0 }],
    grouping: undefined,
  });
  const review = structuredClone(load("event-review", reviewFixture));
  review.session_id = sid;
  review.duration_ms = 120000;
  for (const item of review.items) {
    item.status = "current";
    for (const event of [item.original, item.effective]) {
      event.session_id = sid;
      event.asset_id = aid;
      event.start_ms = 13000;
      event.end_ms = 15000;
    }
  }
  expect(projectMarkers(d, session, review)[0]?.atMs).toBe(500);
  const ids = (d.project.tracks[0]?.segments ?? []).map((s) => s.id).reverse();
  expect(projectMarkers(applyCommand(d, { kind: "reorder", ids }), session, review)[0]?.atMs).toBe(
    11500,
  );
  const stale = structuredClone(review);
  if (stale.items[0]) stale.items[0].status = "stale";
  expect(projectMarkers(d, session, stale)).toEqual([]);
  expect(projectMarkers(d, session, { ...review, session_id: "other" })).toEqual([]);
});
