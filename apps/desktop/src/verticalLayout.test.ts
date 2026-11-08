// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, it } from "vitest";
import type { Profile, VerticalCrop } from "@openworld-moments/contracts";
import goldens from "../../../fixtures/synthetic/vertical-layout-v1.json";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { load } from "@openworld-moments/contracts";
import { FIT, fitRect, pixels, regionAt, suggest, layoutWarnings } from "./verticalLayout";
import { applyCommand, EditorHistory } from "./editor";
for (const c of goldens.cases)
  it(`golden ${c.name}`, () => {
    const r = pixels(
      regionAt(c.layout as VerticalCrop, c.at_ms),
      required(c.size[0]),
      required(c.size[1]),
    );
    expect(r).toEqual(c.pixels);
    expect(fitRect(r[2], r[3])).toEqual(c.fit);
  });
const p = {
  frame: { min_width: 1, min_height: 1, aspect_ratios: ["16:9"] },
  regions: { left: [0, 0.8, 0.2, 0.2], right: [0.8, 0, 0.2, 0.2] },
  safe_zones: { preserve: ["left", "right"] },
} as unknown as Profile;
it("falls back for missing/conflicting regions and ignores rapid scene changes", () => {
  expect(suggest(1920, 1080).layout).toEqual(FIT);
  expect(suggest(1920, 1080, p).layout).toEqual(FIT);
  const profile = { ...p, safe_zones: { preserve: ["left"] }, subject_hints: ["left"] };
  const a = suggest(1920, 1080, profile);
  expect(a.layout.strategy).toBe("fixed");
  expect(a.confidence).toBe(0.65);
  // Subject hints are static profile data; no motion samples can produce jitter.
  for (let t = 0; t < 10000; t += 17) expect(regionAt(a.layout, t)).toEqual(regionAt(a.layout, 0));
  expect(layoutWarnings(a.layout, 1920, 1080, profile)).toEqual([]);
});
it("manual replacement, trim/split/reorder, undo and invalid refusal keep horizontal crops", () => {
  const doc = load("editor-project", structuredClone(fixture)),
    cut = required(required(doc.project.tracks[0]).segments[0]);
  const h = new EditorHistory(doc),
    v = required(goldens.cases.at(-1)).layout as VerticalCrop;
  h.execute({ kind: "vertical-crop", id: cut.id, layout: v });
  expect(required(required(h.document.project.tracks[0]).segments[0]).crop).toEqual(cut.crop);
  expect(h.undo()).toEqual(doc);
  h.redo();
  const split = applyCommand(h.document, {
    kind: "split",
    id: cut.id,
    at_ms: 500,
    new_id: "seg_00000000000000000000000111",
  });
  expect(
    required(
      required(required(required(split.project.tracks[0]).segments[1]).vertical_crop).keyframes[0],
    ).region,
  ).toEqual(regionAt(v, 500));
  expect(() =>
    h.execute({
      kind: "vertical-crop",
      id: cut.id,
      layout: { ...v, keyframes: [{ at_ms: 0, region: [0.9, 0, 0.3, 1] }] },
    }),
  ).toThrow();
  expect(required(required(h.document.project.tracks[0]).segments[0]).vertical_crop).toEqual(v);
});

function required<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error("Missing fixture value");
  return value;
}

it("warns when a moving HUD crosses a narrow blur between key samples", () => {
  const profile = {
    ...p,
    regions: { hud: [0.5, 0.1, 0.01, 0.02] },
    safe_zones: { preserve: ["hud"] },
  } as Profile;
  const layout: VerticalCrop = {
    ...FIT,
    strategy: "keyed",
    keyframes: [
      { at_ms: 0, region: [0, 0, 0.8, 1] },
      { at_ms: 1000, region: [0.2, 0, 0.8, 1] },
    ],
  };
  expect(
    layoutWarnings(layout, 1920, 1080, profile, [{ region: [0.56, 0.34, 0.02, 0.02] }]),
  ).toEqual(["Protected region hud: a privacy blur may obscure it."]);
});

it("warns when a moving blur crosses a protected region between keys", () => {
  const profile = {
    ...p,
    regions: { center: [0.4, 0.4, 0.2, 0.2] },
    safe_zones: { preserve: ["center"] },
  } as unknown as Profile;
  expect(
    layoutWarnings(FIT, 1920, 1080, profile, [
      {
        region: [0, 0.45, 0.05, 0.05],
        keyframes: [{ region: [0, 0.45, 0.05, 0.05] }, { region: [0.95, 0.45, 0.05, 0.05] }],
      },
    ])[0],
  ).toContain("privacy blur");
});
