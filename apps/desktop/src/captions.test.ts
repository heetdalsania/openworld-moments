// SPDX-License-Identifier: AGPL-3.0-or-later
import srtGolden from "./testing/captions.srt?raw";
import vttGolden from "./testing/captions.vtt?raw";
import { expect, it } from "vitest";
import { load, type Caption } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import transcriptFixture from "../../../packages/contracts/fixtures/transcript/valid/two-clips.json";
import profileFixture from "../../../profiles/generic-text/profile.json";
import { must } from "./testing/fakeHost";
import { applyCommand, EditorHistory } from "./editor";
import {
  captionConflicts,
  captionsFromTranscript,
  DEFAULT_CAPTIONS,
  parseCaptions,
  serializeCaptions,
} from "./captions";
const cues: Caption[] = [
  { start_ms: 0, end_ms: 1234, text: "Café & <bridge> → 🚗\n你好, world" },
  { start_ms: 360000123, end_ms: 360001999, text: "Second line" },
];
it.each(["srt", "vtt"] as const)(
  "round trips Unicode/multiline %s golden bytes, BOM and CRLF",
  (format) => {
    const output = serializeCaptions(cues, format);
    expect(output).toBe(format === "srt" ? srtGolden : vttGolden);
    expect(parseCaptions(output, format)).toEqual(cues);
    expect(parseCaptions("\uFEFF" + output.replaceAll("\n", "\r\n"), format)).toEqual(cues);
    expect(parseCaptions(serializeCaptions([], format), format)).toEqual([]);
  },
);
it("refuses malformed, nonfinite, unsafe, markup and blank-line sidecars without modifying text", () => {
  for (const text of ["\nleading", "trailing\n", "a\n\nb", "a\n \nb", "nul\0", "\ud800"]) {
    expect(() => serializeCaptions([{ ...must(cues[0]), text }], "vtt")).toThrow();
  }
  for (const text of [
    "WEBVTT\n\n1\n00:60:00.000 --> 00:61:00.000\nx\n",
    "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\n<script>\n",
    "WEBVTT\n\n1\n00:00:01.000 --> 00:00:00.000\nx\n",
  ])
    expect(() => parseCaptions(text, "vtt")).toThrow();
  expect(() => serializeCaptions([{ start_ms: NaN, end_ms: 10, text: "bad" }], "srt")).toThrow();
  expect(() =>
    serializeCaptions([{ start_ms: 0, end_ms: Number.MAX_SAFE_INTEGER + 1, text: "bad" }], "srt"),
  ).toThrow();
});
it("caption commands sort, retime, split and merge with exact undo/redo; invalid commands are atomic", () => {
  const d = structuredClone(load("editor-project", fixture));
  d.project.captions = [];
  const history = new EditorHistory(d);
  history.execute({
    kind: "captions",
    operation: { action: "add", cue: { start_ms: 1000, end_ms: 2000, text: "🚗 hello" } },
  });
  history.execute({
    kind: "captions",
    operation: { action: "add", cue: { start_ms: 0, end_ms: 500, text: "first" } },
  });
  expect(history.document.project.captions.map((c) => c.start_ms)).toEqual([0, 1000]);
  history.execute({
    kind: "captions",
    operation: { action: "split", index: 1, at_ms: 1500, left: "🚗", right: "hello" },
  });
  expect(history.document.project.captions).toHaveLength(3);
  history.execute({ kind: "captions", operation: { action: "merge", index: 1 } });
  expect(history.document.project.captions[1]?.text).toBe("🚗\nhello");
  const saved = history.document;
  expect(() =>
    history.execute({
      kind: "captions",
      operation: { action: "update", index: 0, cue: { start_ms: -1, end_ms: 20, text: "bad" } },
    }),
  ).toThrow();
  expect(() =>
    history.execute({
      kind: "captions",
      operation: { action: "split", index: 0, at_ms: 0, left: "a", right: "b" },
    }),
  ).toThrow();
  expect(history.document).toEqual(saved);
  history.undo();
  history.redo();
  expect(history.document).toEqual(saved);
  const moved = history.execute({
    kind: "captions",
    operation: { action: "update", index: 0, cue: { start_ms: 2200, end_ms: 2500, text: "moved" } },
  });
  expect(moved.project.captions.map((c) => c.start_ms)).toEqual([1000, 2200]);
  history.execute({ kind: "captions", operation: { action: "remove", index: 1 } });
  expect(history.document.project.captions).toHaveLength(1);
});
it("maps transcript source/word times into trimmed, reordered and repeated cut instances", () => {
  const d = structuredClone(load("editor-project", fixture));
  const t = structuredClone(load("transcript", transcriptFixture));
  t.session_id = d.project.session_id ?? "";
  const first = must(t.segments[0]);
  first.asset_id = must(d.sources[0]).asset_id;
  first.source_start_ms = 13000;
  first.source_end_ms = 15000;
  first.start_ms = 13000;
  first.end_ms = 15000;
  first.words = [
    {
      text: "Hello",
      start_ms: 13000,
      end_ms: 13500,
      source_start_ms: 13000,
      source_end_ms: 13500,
      confidence: 1,
    },
    {
      text: "world",
      start_ms: 14000,
      end_ms: 15000,
      source_start_ms: 14000,
      source_end_ms: 15000,
      confidence: 1,
    },
  ];
  t.segments = [first];
  expect(captionsFromTranscript(d, t, "words").map((c) => [c.start_ms, c.end_ms, c.text])).toEqual([
    [500, 1000, "Hello"],
    [1500, 2500, "world"],
  ]);
  const added = applyCommand(d, {
    kind: "add",
    index: 1,
    segment: {
      ...must(must(d.project.tracks[0]).segments[0]),
      id: "seg_01JCBQ00000000000000000088",
    },
  });
  expect(captionsFromTranscript(added, t, "segments")).toHaveLength(2);
  expect(() => captionsFromTranscript(d, { ...t, session_id: "ses_other" }, "words")).toThrow();
  must(d.sources[0]).requires_relink = true;
  expect(() => captionsFromTranscript(d, t, "segments")).toThrow();
});
it("warns about protected HUD/subtitle intersections using fit geometry", () => {
  const profile = structuredClone(load("profile", profileFixture));
  profile.regions = { subtitle: [0, 0.75, 1, 0.2], hud: [0, 0, 1, 0.1] };
  profile.safe_zones = { preserve: ["hud"] };
  expect(captionConflicts(DEFAULT_CAPTIONS, profile, 16 / 9, 16 / 9)).toContain("hud");
  expect(
    captionConflicts(
      { ...DEFAULT_CAPTIONS, region: [0.08, 0.76, 0.84, 0.18] },
      profile,
      16 / 9,
      16 / 9,
    ),
  ).toContain("subtitle");
  expect(captionConflicts(DEFAULT_CAPTIONS, profile, 16 / 9, 9 / 16)).toEqual([]);
});
