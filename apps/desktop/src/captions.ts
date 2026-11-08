// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  load,
  type Caption,
  type CaptionSettings,
  type EditorProject,
  type Profile,
  type Region,
  type Transcript,
} from "@openworld-moments/contracts";

export const DEFAULT_CAPTIONS: CaptionSettings = {
  preset: "high-contrast",
  region: [0.08, 0.06, 0.84, 0.18],
  burn_in: false,
  sidecar: "none",
};
export type CaptionOperation =
  | { action: "add"; cue: Caption }
  | { action: "update"; index: number; cue: Caption }
  | { action: "remove"; index: number }
  | { action: "split"; index: number; at_ms: number; left: string; right: string }
  | { action: "merge"; index: number }
  | { action: "replace"; cues: Caption[] };

export function orderedCaptions(cues: Caption[]): Caption[] {
  return structuredClone(cues).sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms);
}
export function editCaptions(cues: Caption[], op: CaptionOperation): Caption[] {
  const out = structuredClone(cues);
  const at = (index: number) => {
    if (!Number.isInteger(index) || index < 0 || !out[index])
      throw new Error("Choose an existing caption.");
    return out[index];
  };
  switch (op.action) {
    case "add":
      out.push(structuredClone(op.cue));
      break;
    case "update":
      at(op.index);
      out[op.index] = structuredClone(op.cue);
      break;
    case "remove":
      at(op.index);
      out.splice(op.index, 1);
      break;
    case "replace":
      return orderedCaptions(op.cues);
    case "split": {
      const cue = at(op.index);
      if (!Number.isSafeInteger(op.at_ms) || op.at_ms <= cue.start_ms || op.at_ms >= cue.end_ms)
        throw new Error("Split inside the caption.");
      out.splice(
        op.index,
        1,
        { ...cue, end_ms: op.at_ms, text: op.left },
        { ...cue, start_ms: op.at_ms, text: op.right },
      );
      break;
    }
    case "merge": {
      const a = at(op.index),
        b = at(op.index + 1);
      out.splice(op.index, 2, {
        start_ms: Math.min(a.start_ms, b.start_ms),
        end_ms: Math.max(a.end_ms, b.end_ms),
        text: a.text + "\n" + b.text,
      });
      break;
    }
    default:
      throw new Error("Unknown caption operation.");
  }
  return orderedCaptions(out);
}

/** Use source coordinates, so trims, overlaps, reordered and repeated cuts stay aligned. */
export function captionsFromTranscript(
  document: EditorProject,
  input: Transcript,
  mode: "segments" | "words",
): Caption[] {
  if (mode !== "segments" && mode !== "words") throw new Error("Unknown transcript timing mode.");
  const transcript = load("transcript", input);
  if (!document.project.session_id || transcript.session_id !== document.project.session_id)
    throw new Error("Transcript belongs to another session.");
  const result: Caption[] = [];
  for (const cut of document.project.tracks[0]?.segments ?? []) {
    const binding = document.sources.find((s) => s.asset_id === cut.asset_id);
    if (!binding || binding.requires_relink || binding.replaces_sha256)
      throw new Error("Transcript source identity is unresolved or replaced.");
    for (const span of transcript.segments.filter((s) => s.asset_id === cut.asset_id)) {
      const units = mode === "words" && span.words.length ? span.words : [span];
      for (const unit of units) {
        const start = Math.max(cut.source_in_ms, unit.source_start_ms),
          end = Math.min(cut.source_out_ms, unit.source_end_ms);
        if (start >= end) continue;
        if (unit.text.length > 1000)
          throw new Error(
            "A transcript cue exceeds 1,000 characters. Use word timing or add it manually.",
          );
        result.push({
          start_ms: cut.timeline_start_ms + start - cut.source_in_ms,
          end_ms: cut.timeline_start_ms + end - cut.source_in_ms,
          text: unit.text,
        });
        if (result.length > 10000) throw new Error("Caption limit is 10,000 cues.");
      }
    }
  }
  return orderedCaptions(result);
}

export function captionConflicts(
  settings: CaptionSettings,
  profile: Profile,
  sourceAspect: number,
  frameAspect: number,
): string[] {
  const fitWidth = Math.min(1, sourceAspect / frameAspect),
    fitHeight = Math.min(1, frameAspect / sourceAspect);
  const region = settings.region;
  return Object.entries(profile.regions)
    .filter(
      ([name]) => profile.safe_zones?.preserve.includes(name) || /subtitle|hud|chat/i.test(name),
    )
    .flatMap(([name, r]) => {
      if (!r) return [];
      const mapped: Region = [
        (1 - fitWidth) / 2 + r[0] * fitWidth,
        (1 - fitHeight) / 2 + r[1] * fitHeight,
        r[2] * fitWidth,
        r[3] * fitHeight,
      ];
      return region[0] < mapped[0] + mapped[2] &&
        mapped[0] < region[0] + region[2] &&
        region[1] < mapped[1] + mapped[3] &&
        mapped[1] < region[1] + region[3]
        ? [name]
        : [];
    });
}

export type SidecarFormat = "srt" | "vtt";
function valid(cues: Caption[]): Caption[] {
  if (cues.length > 10000) throw new Error("Caption limit is 10,000 cues.");
  for (const c of cues) {
    if (
      !Number.isSafeInteger(c.start_ms) ||
      !Number.isSafeInteger(c.end_ms) ||
      c.start_ms < 0 ||
      c.end_ms <= c.start_ms ||
      !c.text.length ||
      c.text.length > 1000 ||
      [...c.text].some((ch) => {
        const n = ch.codePointAt(0) ?? 0;
        return (n < 32 && n !== 9 && n !== 10) || n === 127;
      }) ||
      /[\uD800-\uDFFF]/u.test(c.text) ||
      c.text.startsWith("\n") ||
      c.text.endsWith("\n") ||
      c.text.split("\n").some((line) => line.trim().length === 0)
    )
      throw new Error(
        "Sidecar cues need valid millisecond ranges and 1–1,000 characters without blank lines or control characters.",
      );
  }
  return orderedCaptions(cues);
}
function stamp(ms: number, format: SidecarFormat): string {
  const hours = Math.floor(ms / 3600000),
    min = Math.floor(ms / 60000) % 60,
    sec = Math.floor(ms / 1000) % 60;
  return `${String(hours).padStart(2, "0")}:${String(min).padStart(2, "0")}:${String(sec).padStart(2, "0")}${format === "srt" ? "," : "."}${String(ms % 1000).padStart(3, "0")}`;
}
function escaped(text: string): string {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
/** Plain-text subset: no styling, cue settings, markup execution or silent text loss. */
export function serializeCaptions(cues: Caption[], format: SidecarFormat): string {
  if (format !== "srt" && format !== "vtt") throw new Error("Unknown sidecar format.");
  const blocks = valid(cues).map(
    (c, i) =>
      `${i + 1}\n${stamp(c.start_ms, format)} --> ${stamp(c.end_ms, format)}\n${format === "vtt" ? escaped(c.text) : c.text}`,
  );
  const result =
    (format === "vtt" ? "WEBVTT\n\n" : "") + blocks.join("\n\n") + (blocks.length ? "\n" : "");
  if (new TextEncoder().encode(result).length > 4 * 1024 * 1024)
    throw new Error("Sidecar exceeds 4 MiB.");
  return result;
}
export function parseCaptions(text: string, format: SidecarFormat): Caption[] {
  if (format !== "srt" && format !== "vtt") throw new Error("Unknown sidecar format.");
  if (new TextEncoder().encode(text).length > 4 * 1024 * 1024)
    throw new Error("Sidecar exceeds 4 MiB.");
  let body = text.replace(/^\uFEFF/, "").replaceAll("\r\n", "\n");
  if (format === "vtt") {
    if (!body.startsWith("WEBVTT\n\n")) throw new Error("Expected a plain WEBVTT header.");
    body = body.slice(8);
  }
  if (body.endsWith("\n")) body = body.slice(0, -1);
  if (!body) return [];
  const time = (s: string) => {
    if ((format === "srt") !== s.includes(",")) throw new Error("Wrong caption time separator.");
    const match = /^(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})$/.exec(s);
    if (!match || Number(match[2]) > 59 || Number(match[3]) > 59)
      throw new Error("Invalid caption time.");
    return (
      Number(match[1]) * 3600000 +
      Number(match[2]) * 60000 +
      Number(match[3]) * 1000 +
      Number(match[4])
    );
  };
  const cues = body.split("\n\n").map((block, i) => {
    const lines = block.split("\n");
    if (lines.shift() !== String(i + 1)) throw new Error("Expected sequential caption numbers.");
    const range = lines.shift()?.split(" --> ");
    if (!range || range.length !== 2) throw new Error("Invalid caption timing line.");
    const content = lines.join("\n");
    if (format === "vtt" && /[<>]/.test(content))
      throw new Error("Caption markup is unsupported; use plain text.");
    return {
      start_ms: time(range[0] ?? ""),
      end_ms: time(range[1] ?? ""),
      text:
        format === "srt"
          ? content
          : content.replace(
              /&(amp|lt|gt);/g,
              (_, name: string) => ({ amp: "&", lt: "<", gt: ">" })[name] ?? "",
            ),
    };
  });
  return valid(cues);
}
