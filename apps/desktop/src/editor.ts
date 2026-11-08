// SPDX-License-Identifier: AGPL-3.0-or-later
/** Pure M21 command model. No IO, clocks, media writes, or implicit source choices. */
import {
  formatVersion,
  SUPPORTED_VERSION,
  load,
  type EditorProject,
  type Project,
  type Segment,
} from "@openworld-moments/contracts";

import { editCaptions, type CaptionOperation } from "./captions";
import { editAudio, type AudioOperation } from "./editorAudio";
import { retimeBlur } from "./privacyBlur";
import { trimVertical } from "./verticalLayout";

export type EditorCommand =
  | { kind: "captions"; operation: CaptionOperation }
  | { kind: "audio"; operation: AudioOperation }
  | { kind: "caption-settings"; settings: NonNullable<Project["caption_settings"]> }
  | { kind: "vertical-crop"; id: string; layout: NonNullable<Segment["vertical_crop"]> }
  | { kind: "add"; segment: Segment; index: number }
  | { kind: "trim"; id: string; source_in_ms: number; source_out_ms: number }
  | { kind: "split"; id: string; at_ms: number; new_id: string }
  | { kind: "delete"; id: string }
  | { kind: "reorder"; ids: string[] }
  | {
      kind: "settings";
      title?: string;
      layout?: EditorProject["layout"];
      captions?: Project["captions"];
      overlays?: Project["overlays"];
      audio?: Project["audio"];
    };

const copy = <T>(value: T): T => structuredClone(value);
const length = (s: Segment): number => s.source_out_ms - s.source_in_ms;
function integer(n: number): void {
  if (!Number.isSafeInteger(n)) throw new Error("Expected a safe integer");
}

/** Hold crop values between keyframes. Trim/split carry the active crop into the new origin. */
function crop(s: Segment, from: number, to: number): Segment["crop"] {
  const offset = from - s.source_in_ms;
  const keys = s.crop.keyframes;
  const active = keys.filter((k) => k.at_ms <= offset).at(-1);
  return {
    mode: s.crop.mode,
    keyframes: [
      ...(active ? [{ ...copy(active), at_ms: 0 }] : []),
      ...keys
        .filter((k) => k.at_ms > offset && k.at_ms < to - s.source_in_ms)
        .map((k) => ({ ...copy(k), at_ms: k.at_ms - offset })),
    ],
  };
}

interface Timed {
  start_ms: number;
  end_ms: number;
}
/** Annotations follow retained source content, including split and reordered clips. */
function retime<T extends Timed>(
  items: T[],
  before: Segment[],
  after: Segment[],
  parents: Map<string, string>,
): T[] {
  const old = new Map(before.map((s) => [s.id, s]));
  return after
    .flatMap((next) => {
      const prev = old.get(parents.get(next.id) ?? next.id);
      if (!prev) return [];
      const from = Math.max(prev.source_in_ms, next.source_in_ms);
      const to = Math.min(prev.source_out_ms, next.source_out_ms);
      const oldStart = prev.timeline_start_ms + from - prev.source_in_ms;
      const oldEnd = prev.timeline_start_ms + to - prev.source_in_ms;
      return items.flatMap((item) => {
        const a = Math.max(item.start_ms, oldStart),
          b = Math.min(item.end_ms, oldEnd);
        const shift = next.timeline_start_ms + from - next.source_in_ms - oldStart;
        if (a >= b) return [];
        const maybeBlur = item as T & { kind?: string };
        if (maybeBlur.kind === "blur")
          return [
            retimeBlur(
              item as unknown as import("@openworld-moments/contracts").BlurOverlay,
              oldStart,
              oldEnd,
              shift,
            ) as unknown as T,
          ];
        return [{ ...copy(item), start_ms: a + shift, end_ms: b + shift }];
      });
    })
    .sort((a, b) => a.start_ms - b.start_ms);
}

/** Validate both sides. A rejected command cannot mutate the input or history. */
export function applyCommand(document: EditorProject, command: EditorCommand): EditorProject {
  load("editor-project", document);
  const out = copy(document),
    p = out.project;
  const track = p.tracks[0];
  if (!track) throw new Error("Missing primary track");
  const segments = track.segments;
  const before = copy(segments),
    parents = new Map<string, string>();
  const find = (id: string): number => {
    const i = segments.findIndex((s) => s.id === id);
    if (i < 0) throw new Error("Unknown segment");
    return i;
  };
  const segment = (id: string): Segment => {
    const value = segments[find(id)];
    if (!value) throw new Error("Unknown segment");
    return value;
  };
  switch (command.kind) {
    case "captions":
    case "audio":
    case "caption-settings": {
      if (command.kind === "captions") p.captions = editCaptions(p.captions, command.operation);
      else if (command.kind === "audio")
        p.audio = editAudio(
          p.audio,
          command.operation,
          segments.reduce((n, s) => n + length(s), 0),
        );
      else p.caption_settings = copy(command.settings);
      out.schema_version = p.schema_version = formatVersion(SUPPORTED_VERSION);
      return copy(load("editor-project", out));
    }
    case "vertical-crop":
      segment(command.id).vertical_crop = copy(command.layout);
      out.schema_version = p.schema_version = formatVersion(SUPPORTED_VERSION);
      return copy(load("editor-project", out));
    case "add":
      integer(command.index);
      if (command.index < 0 || command.index > segments.length)
        throw new Error("Invalid insertion index");
      if (segments.some((s) => s.id === command.segment.id))
        throw new Error("Duplicate segment ID");
      segments.splice(command.index, 0, copy(command.segment));
      break;
    case "trim": {
      integer(command.source_in_ms);
      integer(command.source_out_ms);
      const s = segment(command.id);
      if (s.vertical_crop)
        s.vertical_crop = trimVertical(s, command.source_in_ms, command.source_out_ms);
      s.crop = crop(s, command.source_in_ms, command.source_out_ms);
      s.source_in_ms = command.source_in_ms;
      s.source_out_ms = command.source_out_ms;
      break;
    }
    case "split": {
      integer(command.at_ms);
      const i = find(command.id),
        s = segment(command.id);
      if (command.at_ms <= 0 || command.at_ms >= length(s))
        throw new Error("Split must be inside segment");
      if (segments.some((x) => x.id === command.new_id)) throw new Error("Duplicate segment ID");
      const middle = s.source_in_ms + command.at_ms;
      const right = {
        ...copy(s),
        id: command.new_id,
        source_in_ms: middle,
        crop: crop(s, middle, s.source_out_ms),
        ...(s.vertical_crop ? { vertical_crop: trimVertical(s, middle, s.source_out_ms) } : {}),
      };
      if (s.vertical_crop) s.vertical_crop = trimVertical(s, s.source_in_ms, middle);
      s.crop = crop(s, s.source_in_ms, middle);
      s.source_out_ms = middle;
      segments.splice(i + 1, 0, right);
      parents.set(right.id, s.id);
      break;
    }
    case "delete":
      segments.splice(find(command.id), 1);
      break;
    case "reorder": {
      if (command.ids.length !== segments.length || new Set(command.ids).size !== segments.length)
        throw new Error("Reorder must be a permutation");
      const reordered = command.ids.map(segment);
      segments.splice(0, segments.length, ...reordered);
      break;
    }
    case "settings": {
      if (command.title !== undefined) p.title = command.title;
      if (command.layout !== undefined) out.layout = copy(command.layout);
      if (command.captions !== undefined) p.captions = copy(command.captions);
      if (command.overlays !== undefined) {
        p.overlays = copy(command.overlays);
        if (p.overlays.some((o) => o.kind === "blur" && o.keyframes))
          out.schema_version = p.schema_version = formatVersion(SUPPORTED_VERSION);
      }
      if (command.audio !== undefined) p.audio = copy(command.audio);
      return copy(load("editor-project", out));
    }
    default:
      throw new Error("Unknown editor command");
  }
  let position = 0;
  for (const s of segments) {
    s.timeline_start_ms = position;
    position += length(s);
  }
  p.captions = retime(p.captions, before, segments, parents);
  p.overlays = retime(p.overlays, before, segments, parents);
  p.audio.mute_ranges = retime(p.audio.mute_ranges, before, segments, parents);
  if (p.audio.gain_ranges)
    p.audio.gain_ranges = retime(p.audio.gain_ranges, before, segments, parents);
  return copy(load("editor-project", out));
}

/** Reversible commands retain exact before/after values; redo never reruns IDs or clocks. */
export class EditorHistory {
  #document: EditorProject;
  #undo: { before: EditorProject; after: EditorProject }[] = [];
  #redo: { before: EditorProject; after: EditorProject }[] = [];
  constructor(
    document: EditorProject,
    readonly limit = 100,
  ) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000)
      throw new Error("History limit must be 1..1000");
    this.#document = copy(load("editor-project", document));
  }
  get document(): EditorProject {
    return copy(this.#document);
  }
  get canUndo(): boolean {
    return this.#undo.length > 0;
  }
  get canRedo(): boolean {
    return this.#redo.length > 0;
  }
  execute(command: EditorCommand): EditorProject {
    const after = applyCommand(this.#document, command);
    this.#undo.push({ before: this.#document, after });
    this.#undo = this.#undo.slice(-this.limit);
    // 16 MiB of serialized snapshots in addition to the count bound. Keep the latest
    // reversible command even for large in-memory documents; persistence caps each at 4 MiB.
    while (this.#undo.length > 1 && JSON.stringify(this.#undo).length * 2 > 16 * 1024 * 1024)
      this.#undo.shift();
    this.#redo = [];
    this.#document = after;
    return this.document;
  }
  undo(): EditorProject {
    const entry = this.#undo.pop();
    if (entry) {
      this.#redo.push(entry);
      this.#document = entry.before;
    }
    return this.document;
  }
  redo(): EditorProject {
    const entry = this.#redo.pop();
    if (entry) {
      this.#undo.push(entry);
      this.#document = entry.after;
    }
    return this.document;
  }
}
