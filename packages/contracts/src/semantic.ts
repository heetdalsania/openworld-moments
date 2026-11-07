// SPDX-License-Identifier: Apache-2.0
// Rules JSON Schema cannot express. Mirrors semantic.py; shared fixtures keep them aligned.
import type {
  AssetDerivedMedia,
  AssetOverlap,
  Session,
  Event,
  Evidence,
  ExportManifest,
  ImportResult,
  Job,
  JobEvent,
  Profile,
  Project,
  Region,
  RenderPreset,
  WatchedFolder,
} from "./generated/types.ts";

const EPSILON = 1e-9;

// Python's '{:g}' formatting for the sums we report.
function g(n: number): string {
  return Number(n.toPrecision(6)).toString();
}

function* region(path: string, r: Region): Generator<string> {
  const [x, y, w, h] = r;
  if (x + w > 1 + EPSILON) {
    yield `${path}: region extends past the right edge (x + width = ${g(x + w)} > 1)`;
  }
  if (y + h > 1 + EPSILON) {
    yield `${path}: region extends past the bottom edge (y + height = ${g(y + h)} > 1)`;
  }
}

function* range(path: string, start: number, end: number, strict = false): Generator<string> {
  if (end < start || (strict && end === start)) {
    const relation = strict ? "greater than" : "at least";
    yield `${path}: end (${end}) must be ${relation} start (${start})`;
  }
}

function* evidence(path: string, item: Evidence): Generator<string> {
  if ("region" in item) yield* region(`${path}.region`, item.region);
  if (item.kind === "ocr" && item.lines) {
    for (const [i, line] of item.lines.entries()) {
      yield* region(`${path}.lines[${i}].region`, line.region);
      const [x, y, w, h] = line.region;
      const [rx, ry, rw, rh] = item.region;
      if (x < rx || y < ry || x + w > rx + rw + 1e-9 || y + h > ry + rh + 1e-9) {
        yield `${path}.lines[${i}].region: line lies outside the OCR region`;
      }
    }
  }
  if ("start_ms" in item) yield* range(`${path}.end_ms`, item.start_ms, item.end_ms);
}

function* event(doc: Event): Generator<string> {
  yield* range("end_ms", doc.start_ms, doc.end_ms);
  if (doc.source.kind === "detector" && doc.evidence.length === 0) {
    yield "evidence: detector observations need at least one piece of evidence";
  }
  for (const [i, item] of doc.evidence.entries()) yield* evidence(`evidence[${i}]`, item);
}

function* job(doc: Job): Generator<string> {
  const p = doc.progress;
  if (p && p.done > p.total) yield `progress: done (${p.done}) exceeds total (${p.total})`;
  if (doc.state === "failed" && doc.error === undefined) {
    yield "error: failed jobs must include an error";
  }
  const present = (["created_at", "started_at", "finished_at"] as const).flatMap((key) => {
    const value = doc[key];
    return value === undefined ? [] : [{ key, time: Date.parse(value) }];
  });
  for (const [i, later] of present.entries()) {
    const earlier = present[i - 1];
    if (earlier && later.time < earlier.time) {
      yield `${later.key}: must not be before ${earlier.key}`;
    }
  }
}

function* jobEvent(doc: JobEvent): Generator<string> {
  for (const issue of job(doc.job)) yield `job.${issue}`;
}

function* profile(doc: Profile): Generator<string> {
  for (const [name, r] of Object.entries(doc.regions)) {
    if (r) yield* region(`regions.${name}`, r);
  }
  for (const name of doc.safe_zones?.preserve ?? []) {
    if (!(name in doc.regions)) yield `safe_zones.preserve: '${name}' is not defined in regions`;
  }
}

function* project(doc: Project): Generator<string> {
  for (const [t, track] of doc.tracks.entries()) {
    for (const [s, seg] of track.segments.entries()) {
      const path = `tracks[${t}].segments[${s}]`;
      yield* range(`${path}.source_out_ms`, seg.source_in_ms, seg.source_out_ms, true);
      for (const [k, frame] of seg.crop.keyframes.entries()) {
        yield* region(`${path}.crop.keyframes[${k}].region`, frame.region);
      }
    }
  }
  for (const [i, c] of doc.captions.entries()) {
    yield* range(`captions[${i}].end_ms`, c.start_ms, c.end_ms, true);
  }
  for (const [i, o] of doc.overlays.entries()) {
    yield* range(`overlays[${i}].end_ms`, o.start_ms, o.end_ms, true);
    yield* region(`overlays[${i}].region`, o.region);
  }
  for (const [i, m] of doc.audio.mute_ranges.entries()) {
    yield* range(`audio.mute_ranges[${i}].end_ms`, m.start_ms, m.end_ms, true);
  }
}

function* renderPreset(doc: RenderPreset): Generator<string> {
  if ((doc.video.crf !== undefined) === (doc.video.bitrate_kbps !== undefined)) {
    yield "video: set exactly one of 'crf' or 'bitrate_kbps'";
  }
}

function* exportManifest(doc: ExportManifest): Generator<string> {
  const count = doc.sources.length;
  for (const [i, seg] of doc.segments.entries()) {
    if (seg.source >= count) {
      yield `segments[${i}].source: index ${seg.source} is out of range (${count} sources)`;
    }
    yield* range(`segments[${i}].out_ms`, seg.in_ms, seg.out_ms, true);
  }
}

const WITH_ASSET = new Set(["imported", "existing", "relinked"]);

function* importResult(doc: ImportResult): Generator<string> {
  const counts: Record<string, number> = {
    imported: 0,
    existing: 0,
    relinked: 0,
    skipped: 0,
    failed: 0,
  };
  for (const [i, item] of doc.items.entries()) {
    const outcome = item.outcome;
    counts[outcome] = (counts[outcome] ?? 0) + 1;
    if (WITH_ASSET.has(outcome)) {
      if (item.asset_id === undefined) {
        yield `items[${i}].asset_id: '${outcome}' items must name their asset`;
      }
      if (item.error !== undefined) {
        yield `items[${i}].error: '${outcome}' items must not carry an error`;
      }
    } else {
      if (item.error === undefined) yield `items[${i}].error: '${outcome}' items must explain why`;
      if (item.asset_id !== undefined) {
        yield `items[${i}].asset_id: '${outcome}' items must not name an asset`;
      }
      if (item.candidate_asset_ids !== undefined) {
        yield `items[${i}].candidate_asset_ids: '${outcome}' items have no candidates`;
      }
    }
  }
  const totals = doc.totals;
  if (totals.files !== doc.items.length) {
    yield `totals.files: ${totals.files} does not match ${doc.items.length} items`;
  }
  for (const [outcome, count] of Object.entries(counts)) {
    const total = totals[outcome as keyof typeof totals];
    if (total !== count) yield `totals.${outcome}: ${total} does not match ${count} items`;
  }
}

function* watchedFolder(doc: WatchedFolder): Generator<string> {
  const s = doc.stats;
  const counted = s.imported + s.in_progress + s.failed;
  if (counted > s.tracked) {
    yield `stats.tracked: ${s.tracked} is less than the ${counted} files counted by state`;
  }
}

const KINDS = ["proxy", "filmstrip", "waveform"] as const;
const COMPLETE = ["ready", "stale", "missing"];
const COMPLETE_FIELDS = ["cache_key", "path", "size_bytes", "sha256", "created_at", "recipe"];

function* derivedMedia(doc: AssetDerivedMedia): Generator<string> {
  const decision = doc.proxy_decision;
  const real = decision.reasons.filter((r) => r.code !== "no_video");
  if (decision.needed !== real.length > 0) {
    yield "proxy_decision.needed: must be true exactly when there is a reason";
  }
  const kinds = doc.artifacts.map((a) => a.kind);
  if (kinds.join() !== KINDS.join()) {
    yield `artifacts: kinds must be ${KINDS.join(", ")} in that order, got ${kinds.join(", ")}`;
  }
  for (const [i, artifact] of doc.artifacts.entries()) {
    yield* derivedArtifact(artifact as unknown as Record<string, unknown>, i);
  }
}

function* derivedArtifact(art: Record<string, unknown>, i: number): Generator<string> {
  const kind = String(art.kind);
  const status = String(art.status);
  const others = KINDS.filter((k) => k !== kind && k in art);
  if (others.length > 0) {
    yield `artifacts[${i}]: a ${kind} artifact cannot carry ${others.join(", ")} info`;
  }
  if (COMPLETE.includes(status)) {
    for (const field of [...COMPLETE_FIELDS, kind]) {
      if (!(field in art)) yield `artifacts[${i}].${field}: required when status is '${status}'`;
    }
    const path = art.path;
    if (typeof path === "string" && !(path.split("/").pop() ?? "").startsWith(`${kind}-`)) {
      yield `artifacts[${i}].path: does not name a ${kind} artifact`;
    }
  } else {
    for (const field of ["path", "size_bytes", "sha256", "created_at", kind]) {
      if (field in art) yield `artifacts[${i}].${field}: not allowed when status is '${status}'`;
    }
  }
  if (status === "failed" && !("last_error" in art)) {
    yield `artifacts[${i}].last_error: required when status is 'failed'`;
  }
  const info = art[kind] as Record<string, unknown> | undefined;
  if (kind === "filmstrip" && info !== undefined) {
    const times = info.times_ms as number[];
    if (info.count !== times.length) {
      yield `artifacts[${i}].filmstrip.count: ${String(info.count)} != ${times.length} times`;
    }
    if (times.some((t, j) => j > 0 && t <= (times[j - 1] ?? -1))) {
      yield `artifacts[${i}].filmstrip.times_ms: must strictly ascend`;
    }
  }
  if (kind === "proxy" && info !== undefined && info.tone_mapped !== "tone_map" in info) {
    yield `artifacts[${i}].proxy.tone_map: present exactly when tone_mapped is true`;
  }
}

function* session(doc: Session): Generator<string> {
  const members = doc.assets;
  if (members.some((m, i) => m.order_index !== i)) {
    yield "assets: order_index must be 0, 1, 2, … in order";
  }
  if (
    members.some((m, i) => i > 0 && m.session_start_ms < (members[i - 1]?.session_start_ms ?? 0))
  ) {
    yield "assets: session_start_ms must not decrease";
  }
  const ids = members.map((m) => m.asset_id);
  if (new Set(ids).size !== ids.length) yield "assets: an asset appears twice";
  if (doc.started_at && doc.ended_at && Date.parse(doc.ended_at) < Date.parse(doc.started_at)) {
    yield "ended_at: before started_at";
  }
  if ((members[0]?.overlap_with_previous_ms ?? 0) > 0) {
    yield "assets[0].overlap_with_previous_ms: the first clip has nothing before it";
  }
  const pairs = new Set(ids.slice(1).map((id, i) => `${ids[i] ?? ""}>${id}`));
  for (const [i, link] of (doc.grouping?.links ?? []).entries()) {
    if (!pairs.has(`${link.from_asset_id}>${link.to_asset_id}`)) {
      yield `grouping.links[${i}]: must join adjacent members`;
    }
  }
}

function* overlap(doc: AssetOverlap): Generator<string> {
  if (doc.asset_a === doc.asset_b) yield "asset_b: must differ from asset_a";
  if (doc.status === "matched") {
    for (const field of ["offset_ms", "overlap_ms", "confidence"] as const) {
      if (doc[field] === undefined) yield `${field}: required when status is 'matched'`;
    }
  }
  const { applied, override } = doc;
  if (override && (applied.source !== "user" || applied.overlap_ms !== override.overlap_ms)) {
    yield "applied: must be the override when one is set";
  }
  if (!override && applied.source === "auto" && (doc.status !== "matched" || !doc.current)) {
    yield "applied: only a current matched result can be applied";
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- each rule narrows its own input
const RULES: Record<string, (doc: any) => Iterable<string>> = {
  overlap,
  session,
  "derived-media": derivedMedia,
  event,
  job,
  "job-event": jobEvent,
  profile,
  "profile-patch": (doc: Profile) =>
    Object.entries(doc.regions).flatMap(([name, r]) =>
      r ? [...region(`regions.${name}`, r)] : [],
    ),
  project,
  "render-preset": renderPreset,
  "export-manifest": exportManifest,
  import: importResult,
  "watched-folder": watchedFolder,
};

/** Human-readable semantic problems. Assumes the document passed schema validation. */
export function semanticIssues(contract: string, document: unknown): string[] {
  const rule = RULES[contract];
  return rule ? [...rule(document)] : [];
}
