// SPDX-License-Identifier: AGPL-3.0-or-later
import { expect, it } from "vitest";
import {
  load,
  formatVersion,
  SUPPORTED_VERSION,
  type BlurOverlay,
} from "@openworld-moments/contracts";
import goldens from "../../../fixtures/synthetic/privacy-blur-v1.json";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/moving-blur.json";
import { blurPixels, blurRegionAt, retimeBlur } from "./privacyBlur";
import { EditorHistory, applyCommand } from "./editor";
const blur = goldens.blur as BlurOverlay;
for (const c of goldens.cases)
  it(`blur golden ${c.width}x${c.height} at ${c.at_ms}`, () => {
    const r = blurRegionAt(blur, c.at_ms);
    r.forEach((v, i) => expect(v).toBeCloseTo(c.region[i] ?? -1, 10));
    expect(blurPixels(r, c.width, c.height)).toEqual(c.pixels);
  });
it("clips linear keyframes and preserves every retained sample within floating precision", () => {
  const cut = retimeBlur(blur, 800, 1900, 2500);
  for (const t of [800, 900, 1100, 1500, 1899])
    blurRegionAt(cut, t + 2500).forEach((v, i) =>
      expect(v).toBeCloseTo(blurRegionAt(blur, t)[i] ?? -1, 10),
    );
  expect(cut.keyframes?.[0]?.at_ms).toBe(0);
});
it("blur split/reorder/trim and undo keep moving protection on source content", () => {
  const doc = load("editor-project", structuredClone(fixture));
  const first = doc.project.tracks[0]?.segments[0];
  if (!first) throw new Error("fixture cut");
  const history = new EditorHistory(doc);
  const split = history.execute({
    kind: "split",
    id: first.id,
    at_ms: 500,
    new_id: "seg_00000000000000000000000111",
  });
  expect(split.project.overlays.filter((o) => o.kind === "blur")).toHaveLength(2);
  expect(history.undo()).toEqual(doc);
  expect(() =>
    applyCommand(doc, {
      kind: "settings",
      overlays: [
        {
          ...blur,
          keyframes: [
            { at_ms: 0, region: blur.region },
            { at_ms: 1, region: [0, 0, 0.5, 0.5] },
          ],
        },
      ],
    }),
  ).toThrow();
});

it("keeps a full 100-key blur valid when reordering without trimming", () => {
  const keys = Array.from({ length: 100 }, (_, i) => ({
    at_ms: i * 10,
    region: [i / 200, 0.1, 0.2, 0.2] as BlurOverlay["region"],
  }));
  const first = keys[0];
  if (!first) throw new Error("key fixture");
  const full: BlurOverlay = {
    kind: "blur",
    start_ms: 0,
    end_ms: 2000,
    region: first.region,
    keyframes: keys,
  };
  expect(retimeBlur(full, 0, 2000, 3000).keyframes).toHaveLength(100);
});

it("stamps current versions when a legacy project adds moving privacy regions", () => {
  const legacy = structuredClone(load("editor-project", fixture));
  legacy.schema_version = legacy.project.schema_version = "1.0";
  const next = applyCommand(legacy, { kind: "settings", overlays: [blur] });
  expect(next.schema_version).toBe(formatVersion(SUPPORTED_VERSION));
  expect(next.project.schema_version).toBe(next.schema_version);
});
