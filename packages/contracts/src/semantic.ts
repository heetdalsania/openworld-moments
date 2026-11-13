// SPDX-License-Identifier: Apache-2.0
// Rules JSON Schema cannot express. Mirrors semantic.py; shared fixtures keep them aligned.
import type {
  DiagnosticsReport,
  PlatformCapabilities,
  PrivacyReview,
  ModelManager,
  SystemDoctor,
  EventExportLine,
  ExportResult,
  ProjectExport,
  Collection,
  SearchIndexStatus,
  SearchResult,
  SearchResults,
  StoryCandidate,
  StoryCandidates,
  EvaluationManifest,
  EvaluationObservations,
  EventReview,
  AssetDerivedMedia,
  AssetOverlap,
  Session,
  RenderEncoders,
  RenderRecord,
  SpeechModels,
  Transcript,
  TranscriptionResult,
  Event,
  Evidence,
  ExportManifest,
  ImportResult,
  Job,
  JobEvent,
  Profile,
  Project,
  EditorProject,
  Region,
  RenderPreset,
  WatchedFolder,
} from "./generated/types.ts";

import { checkVersion } from "./versioning.ts";

const EPSILON = 1e-9;

// Python's '{:g}' formatting for the sums we report.
function g(n: number): string {
  return Number(n.toPrecision(6)).toString();
}

function* modelManager(doc: ModelManager): Generator<string> {
  if (new Set(doc.models.map((m) => m.name)).size !== doc.models.length)
    yield "models: duplicate model names";
  for (const model of doc.models)
    if (model.downloaded_bytes > model.size_bytes) yield "downloaded_bytes: exceeds signed size";
  for (const model of doc.models) {
    const platforms: string[] = model.platforms ?? [];
    if (platforms.includes("any") && platforms.length > 1)
      yield "platforms: any must be the only entry";
    if (platforms.length === 1 && platforms[0] === "any" && model.compatible === false)
      yield "compatible: a model for any platform is compatible";
  }
}
function* diagnosticsReport(doc: DiagnosticsReport): Generator<string> {
  const omitted = doc.privacy.failure_messages === "omitted";
  if (omitted && doc.jobs.recent_failures.some((f) => f.message !== undefined))
    yield "jobs.recent_failures: messages present although omitted";
  const pairs = doc.jobs.totals.map((t) => `${t.kind}\u0000${t.state}`);
  if (new Set(pairs).size !== pairs.length) yield "jobs.totals: duplicate kind and state";
  if (doc.host !== undefined)
    for (const issue of platformCapabilities(doc.host)) yield `host.${issue}`;
}
const BLOCKING = new Set(["os-below-minimum", "translated", "architecture-unsupported"]);
const FAMILY: Record<string, readonly [string, string]> = {
  windows: ["windows-appdata", "explorer"],
  macos: ["macos-standard", "finder"],
  linux: ["xdg", "xdg-open"],
};
function release(text: string): [number, number, number] {
  const [major = 0, minor = 0, patch = 0] = text.split(".").map(Number);
  return [major, minor, patch];
}
function olderThan(a: [number, number, number], b: [number, number, number]): boolean {
  for (const [x, y] of a.map((value, i) => [value, b[i] ?? 0] as const)) if (x !== y) return x < y;
  return false;
}
function* platformCapabilities(doc: PlatformCapabilities): Generator<string> {
  const level = doc.support.level;
  const reasons = new Set<string>(doc.support.reasons);
  const blocking = [...reasons].some((r) => BLOCKING.has(r));
  if ((level === "unsupported") !== blocking)
    yield "support.level: unsupported exactly when a blocking reason is present";
  if (level === "alpha" && reasons.size > 0)
    yield "support.reasons: an alpha target carries no reasons";
  if (level === "development" && reasons.size === 0)
    yield "support.reasons: a development target needs a reason";
  if ((doc.architecture.translated === true) !== reasons.has("translated"))
    yield "support.reasons: translated must match architecture.translated";
  if ((doc.build.profile === "debug") !== reasons.has("debug-build"))
    yield "support.reasons: debug-build must match build.profile";
  const { version, minimum } = doc.os;
  const below =
    version !== null && minimum !== null && olderThan(release(version), release(minimum));
  if (below !== reasons.has("os-below-minimum"))
    yield "support.reasons: os-below-minimum must match os.version and os.minimum";
  const [convention, fileManager] = FAMILY[doc.os.family] ?? ["", ""];
  if (doc.directories.convention !== convention)
    yield `directories.convention: ${doc.os.family} uses ${convention}`;
  if (doc.integrations.file_manager !== fileManager)
    yield `integrations.file_manager: ${doc.os.family} uses ${fileManager}`;
}
function* systemDoctor(doc: SystemDoctor): Generator<string> {
  if (doc.ready !== !doc.checks.some((c) => c.status === "fail")) yield "ready: must match checks";
  if (new Set(doc.checks.map((c) => c.id)).size !== doc.checks.length)
    yield "checks: duplicate IDs";
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
  for (const name of [...(doc.safe_zones?.preserve ?? []), ...(doc.subject_hints ?? [])]) {
    if (!(name in doc.regions)) yield `safe_zones.preserve: '${name}' is not defined in regions`;
  }
}

function* project(doc: Project): Generator<string> {
  if (doc.caption_settings) yield* region("caption_settings.region", doc.caption_settings.region);
  for (const [t, track] of doc.tracks.entries()) {
    for (const [s, seg] of track.segments.entries()) {
      const path = `tracks[${t}].segments[${s}]`;
      yield* range(`${path}.source_out_ms`, seg.source_in_ms, seg.source_out_ms, true);
      if (seg.vertical_crop) {
        const v = seg.vertical_crop,
          keys = v.keyframes;
        if (
          (v.strategy === "fit" && keys.length !== 0) ||
          (v.strategy === "fixed" && keys.length !== 1) ||
          (v.strategy !== "fit" && keys[0]?.at_ms !== 0)
        )
          yield "vertical_crop: strategy requires fit with no keys or crop starting at zero";
        let prev = -1;
        for (const k of keys) {
          yield* region("vertical_crop.region", k.region);
          if (!(prev < k.at_ms && k.at_ms < seg.source_out_ms - seg.source_in_ms))
            yield "vertical_crop: keys must increase inside cut";
          if (keys[0] && (k.region[2] !== keys[0].region[2] || k.region[3] !== keys[0].region[3]))
            yield "vertical_crop: interpolation requires fixed dimensions";
          prev = k.at_ms;
        }
      }
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
    if (o.kind === "blur" && o.keyframes) {
      if (o.keyframes.length === 0 || o.keyframes[0]?.at_ms !== 0)
        yield "blur: keyframes must start at zero";
      let previous = -1;
      for (const k of o.keyframes) {
        yield* region("blur.keyframe.region", k.region);
        if (!(previous < k.at_ms && k.at_ms < o.end_ms - o.start_ms))
          yield "blur: keyframes must increase inside range";
        if (k.region[2] !== o.region[2] || k.region[3] !== o.region[3])
          yield "blur: keyframes require fixed dimensions";
        previous = k.at_ms;
      }
      if (JSON.stringify(o.keyframes[0]?.region) !== JSON.stringify(o.region))
        yield "blur: region must equal first keyframe";
    }
  }
  for (const [i, m] of doc.audio.mute_ranges.entries()) {
    yield* range(`audio.mute_ranges[${i}].end_ms`, m.start_ms, m.end_ms, true);
  }
  for (const [i, gain] of (doc.audio.gain_ranges ?? []).entries()) {
    yield* range(`audio.gain_ranges[${i}].end_ms`, gain.start_ms, gain.end_ms, true);
  }
}

function* editorProject(doc: EditorProject): Generator<string> {
  const p = doc.project;
  checkVersion("project", p);
  yield* project(p);
  if (p.tracks.length !== 1) {
    yield "project.tracks: editor requires one primary track";
    return;
  }
  const sources = new Map(doc.sources.map((s) => [s.asset_id, s]));
  if (sources.size !== doc.sources.length) yield "sources: duplicate asset ID";
  const segments = p.tracks[0]?.segments ?? [];
  if (segments.length > 4096) yield "project.segments: limit 4096";
  let position = 0;
  const ids = new Set<string>();
  for (const s of segments) {
    const length = s.source_out_ms - s.source_in_ms;
    if (ids.has(s.id)) yield "project.segments: duplicate segment ID";
    ids.add(s.id);
    if (s.timeline_start_ms !== position)
      yield "project.segments: primary track must be contiguous from zero";
    position += length;
    const source = sources.get(s.asset_id);
    if (!source || s.source_out_ms > source.duration_ms)
      yield "project.segments: source binding missing or range exceeds source";
    const keys = s.crop.keyframes;
    if (keys.length > 1000) yield "project.crop: limit 1000 keyframes";
    let last = -1;
    for (const k of keys) {
      if (!(last < k.at_ms && k.at_ms < length))
        yield "project.crop: keyframes must increase inside segment";
      last = k.at_ms;
    }
    if (s.crop.mode === "manual" && keys[0]?.at_ms !== 0)
      yield "project.crop: manual crop needs a keyframe at zero";
  }
  if (position > Number.MAX_SAFE_INTEGER) yield "project: timeline exceeds safe integer range";
  for (const [name, items] of [
    ["captions", p.captions],
    ["overlays", p.overlays],
    ["mute_ranges", p.audio.mute_ranges],
    ["gain_ranges", p.audio.gain_ranges ?? []],
  ] as const) {
    if (items.length > 10000) yield `project.${name}: limit 10000`;
    for (const item of items) {
      if (!(0 <= item.start_ms && item.start_ms < item.end_ms && item.end_ms <= position))
        yield `project.${name}: range outside timeline`;
    }
    if (name === "gain_ranges") {
      const ordered = [...items].sort((a, b) => a.start_ms - b.start_ms);
      if (ordered.some((b, i) => (ordered[i - 1]?.end_ms ?? 0) > b.start_ms))
        yield "project.gain_ranges: overlapping gain ranges";
    }
  }
  if ((doc.layout.profile_id !== undefined) !== (doc.layout.profile_version !== undefined))
    yield "layout: profile ID and version must be supplied together";
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

function* transcript(doc: Transcript): Generator<string> {
  let previous: number | undefined;
  for (const [i, seg] of doc.segments.entries()) {
    const path = `segments[${i}]`;
    yield* range(`${path}.end_ms`, seg.start_ms, seg.end_ms);
    yield* range(`${path}.source_end_ms`, seg.source_start_ms, seg.source_end_ms);
    if (previous !== undefined && seg.start_ms < previous) {
      yield `${path}.start_ms: segments must be ordered by session time`;
    }
    previous = seg.start_ms;
    let last = seg.start_ms;
    for (const [j, word] of seg.words.entries()) {
      const wpath = `${path}.words[${j}]`;
      yield* range(`${wpath}.end_ms`, word.start_ms, word.end_ms);
      yield* range(`${wpath}.source_end_ms`, word.source_start_ms, word.source_end_ms);
      if (word.start_ms < seg.start_ms || word.end_ms > seg.end_ms) {
        yield `${wpath}: word lies outside its segment`;
      }
      if (word.start_ms < last) yield `${wpath}.start_ms: words must be ordered`;
      last = word.start_ms;
    }
  }
}

function* transcription(doc: TranscriptionResult): Generator<string> {
  const seen = new Set<string>();
  for (const [i, outcome] of doc.outcomes.entries()) {
    if (seen.has(outcome.asset_id)) yield `outcomes[${i}].asset_id: each clip appears once`;
    seen.add(outcome.asset_id);
  }
}

function* speechModels(doc: SpeechModels): Generator<string> {
  const names = doc.installed.map((m) => m.name);
  if (new Set(names).size !== names.length) yield "installed: model names must be unique";
  if (!doc.engine.available && doc.engine.reason === undefined) {
    yield "engine.reason: required when the engine is unavailable";
  }
}

function* evaluation(doc: EvaluationManifest | EvaluationObservations): Generator<string> {
  const hashes = doc.clips.map((c) => c.sha256);
  if (new Set(hashes).size !== hashes.length) yield "clips: media hashes must be unique";
  for (const [i, clip] of doc.clips.entries()) {
    const events = "annotations" in clip ? clip.annotations : clip.events;
    for (const [j, event] of events.entries()) {
      if (
        event.end_ms < event.start_ms ||
        ("duration_ms" in clip && event.end_ms > clip.duration_ms)
      )
        yield `clips[${i}].intervals[${j}]: invalid clip interval`;
    }
  }
  if ("detectors" in doc && new Set(doc.detectors.map((d) => d.id)).size !== doc.detectors.length)
    yield "detectors: IDs must be unique";
}

function* eventReview(doc: EventReview): Generator<string> {
  if (doc.offset + doc.items.length > Math.max(doc.total, doc.offset))
    yield "items: page exceeds total";
  if (new Set(doc.items.map((i) => i.original.id)).size !== doc.items.length)
    yield "items: event IDs must be unique";
  for (const [i, item] of doc.items.entries()) {
    const a = item.original,
      b = item.effective;
    for (const [name, e] of [
      ["original", a],
      ["effective", b],
    ] as const)
      for (const issue of event(e)) yield `items[${i}].${name}.${issue}`;
    const keys = [
      "id",
      "session_id",
      "asset_id",
      "confidence",
      "evidence",
      "source",
      "attributes",
    ] as const;
    // Validated JSON maps may have different insertion order in different runtimes.
    const stable = (v: unknown): string =>
      JSON.stringify(
        v && typeof v === "object"
          ? Array.isArray(v)
            ? v.map((x) => stable(x))
            : Object.fromEntries(
                Object.entries(v)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([k, x]) => [k, stable(x)]),
              )
          : v,
      );
    if (a.session_id !== doc.session_id || keys.some((k) => stable(a[k]) !== stable(b[k])))
      yield `items[${i}]: immutable observation fields differ`;
    if (item.status === "current" && b.end_ms > doc.duration_ms)
      yield `items[${i}].effective.end_ms: outside current session`;
    const revisions = item.history.map((d) => d.revision);
    if (
      revisions.length &&
      (revisions.some((r, j) => j > 0 && r <= (revisions[j - 1] ?? 0)) ||
        revisions.at(-1) !== item.revision)
    )
      yield `items[${i}].history: revisions must ascend to current revision`;
    for (const [j, d] of item.history.entries())
      yield* range(`items[${i}].history[${j}].end_ms`, d.start_ms, d.end_ms);
  }
}

function* storyRanges(
  ranges: StoryCandidate["source_ranges"],
  start: number,
  end: number,
): Generator<string> {
  let position = start;
  const used = new Map<string, [number, number][]>();
  for (const r of ranges) {
    if (
      r.session_start_ms !== position ||
      r.session_end_ms <= position ||
      r.source_out_ms - r.source_in_ms !== r.session_end_ms - position
    )
      yield "source_ranges: ranges must cover the window exactly without gaps or duplicate time";
    for (const [a, b] of used.get(r.asset_id) ?? [])
      if (r.source_in_ms < b && a < r.source_out_ms)
        yield "source_ranges: duplicate source footage";
    used.set(r.asset_id, [...(used.get(r.asset_id) ?? []), [r.source_in_ms, r.source_out_ms]]);
    position = r.session_end_ms;
  }
  if (position !== end) yield "source_ranges: end differs from the window";
}
function* storyCandidate(doc: StoryCandidate): Generator<string> {
  yield* range("end_ms", doc.start_ms, doc.end_ms, true);
  const maximum = { moment: 25000, short: 60000, extended_short: 180000, highlight: 120000 }[
    doc.preset
  ];
  if (doc.end_ms - doc.start_ms > maximum) yield "end_ms: preset maximum exceeded";
  yield* storyRanges(doc.source_ranges, doc.start_ms, doc.end_ms);
  const ids = doc.source_events.map((e) => e.event_id);
  if (new Set(ids).size !== ids.length) yield "source_events: event IDs must be unique";
  for (const e of doc.source_events)
    yield* range("source_events.end_ms", e.start_ms, e.end_ms, true);
  for (const b of doc.beats) {
    yield* range("beats.end_ms", b.start_ms, b.end_ms, true);
    if (b.start_ms < doc.start_ms || b.end_ms > doc.end_ms) yield "beats: outside candidate window";
    if (b.event_ids.some((id) => !ids.includes(id))) yield "beats: unknown source event";
  }
  if (
    Math.abs(Object.values(doc.score_components).reduce((a, b) => a + b, 0) - doc.score) > 0.0000011
  )
    yield "score: must equal the sum of score_components";
  const positive = {
    event_confidence: 0.25,
    setup_coverage: 0.15,
    payoff_coverage: 0.2,
    reaction_evidence: 0.1,
    continuity_score: 0.3,
  };
  const negative = {
    duplicate_penalty: 0,
    dead_air_penalty: 0.15,
    truncation_penalty: 0.25,
    spoiler_risk_penalty: 0.1,
    rejection_penalty: 0.2,
    missing_payoff_penalty: 0.1,
  };
  if (
    Object.entries(positive).some(
      ([k, v]) =>
        doc.score_components[k as keyof typeof doc.score_components] < 0 ||
        doc.score_components[k as keyof typeof doc.score_components] > v,
    ) ||
    Object.entries(negative).some(
      ([k, v]) =>
        doc.score_components[k as keyof typeof doc.score_components] < -v ||
        doc.score_components[k as keyof typeof doc.score_components] > 0,
    )
  )
    yield "score_components: component outside documented weight";
  const seen = new Set<string>();
  for (const a of doc.alternatives) {
    yield* range("alternatives.end_ms", a.start_ms, a.end_ms, true);
    if (a.end_ms - a.start_ms > maximum || seen.has(a.kind))
      yield "alternatives: preset maximum or unique kind violated";
    seen.add(a.kind);
    yield* storyRanges(a.source_ranges, a.start_ms, a.end_ms);
  }
}
function* storyCandidates(doc: StoryCandidates): Generator<string> {
  const ids = doc.items.map((i) => i.candidate.id);
  if (new Set(ids).size !== ids.length || (ids.length && doc.offset + ids.length > doc.total))
    yield "items: duplicate IDs or inconsistent page total";
  for (const item of doc.items) {
    const c = item.candidate;
    yield* storyCandidate(c);
    if (c.session_id !== doc.session_id) yield "items: foreign session";
    if (
      item.current &&
      (c.input_key !== doc.input_key ||
        c.layout_key !== doc.layout_key ||
        c.generator.id !== doc.generator.id ||
        c.generator.version !== doc.generator.version ||
        c.end_ms > doc.duration_ms)
    )
      yield "items: current candidate identity or timing differs";
    if (item.revision === 0 && item.review_state !== "suggested")
      yield "items: unrecorded review decision";
    if (item.project_id && item.project_id !== c.id)
      yield "items: project ID differs from candidate";
  }
}

function* renderRecord(doc: RenderRecord): Generator<string> {
  const plan = doc.plan;
  if (plan) {
    for (const [i, source] of plan.sources.entries()) {
      if (source.index !== i) yield `plan.sources[${i}].index: sources are numbered in order`;
    }
    let expected = 0;
    for (const [i, seg] of plan.segments.entries()) {
      const path = `plan.segments[${i}]`;
      if (seg.source >= plan.sources.length) yield `${path}.source: no such source`;
      yield* range(`${path}.out_ms`, seg.in_ms, seg.out_ms, true);
      if (seg.timeline_start_ms !== expected) {
        yield `${path}.timeline_start_ms: segments are contiguous from zero`;
      }
      expected += seg.out_ms - seg.in_ms;
      if (seg.crop.mode === "manual" && seg.crop.region === undefined) {
        yield `${path}.crop.region: required for a manual crop`;
      }
    }
    if (expected !== plan.duration_ms) {
      yield "plan.duration_ms: must equal the sum of segment durations";
    }
  }
  if (doc.status === "ready" && !doc.validation?.passed) {
    yield "validation.passed: a ready render has passed validation";
  }
  if (doc.status !== "failed" && doc.fallback !== undefined) {
    yield "fallback: only a failed render offers a fallback";
  }
}

function* renderEncoders(doc: RenderEncoders): Generator<string> {
  const ids = doc.encoders.map((e) => e.id);
  if (new Set(ids).size !== ids.length) yield "encoders: each encoder appears once";
  for (const [i, encoder] of doc.encoders.entries()) {
    if ((encoder.id === "libx264") !== (encoder.kind === "cpu")) {
      yield `encoders[${i}].kind: libx264 is the CPU encoder; others are hardware`;
    }
    if (!encoder.available && encoder.reason === undefined) {
      yield `encoders[${i}].reason: required when unavailable`;
    }
  }
}

const ID_FIELD = {
  clip: "asset_id",
  session: "session_id",
  event: "event_id",
  transcript: "transcript_id",
  project: "project_id",
} as const;

function* searchResult(path: string, item: SearchResult): Generator<string> {
  const [prefix, ident] = [
    item.key.slice(0, item.key.indexOf(":")),
    item.key.slice(item.key.indexOf(":") + 1),
  ];
  if (prefix !== item.kind) yield `${path}.key: must start with the result kind`;
  const field = ID_FIELD[item.kind];
  if (String(item[field] ?? "") !== ident) yield `${path}.${field}: must match the key`;
  if (item.range) {
    yield* range(`${path}.range.end_ms`, item.range.start_ms, item.range.end_ms);
    if ((item.range.timebase === "clip") !== (item.kind === "clip")) {
      yield `${path}.range.timebase: clip results use clip time; others session time`;
    }
  }
  if (item.source_range) {
    yield* range(
      `${path}.source_range.end_ms`,
      item.source_range.start_ms,
      item.source_range.end_ms,
    );
    if (item.source_range.asset_id !== item.asset_id) {
      yield `${path}.source_range.asset_id: must match the result clip`;
    }
  }
}

function* page(
  doc: { offset: number; total: number; items: SearchResult[] },
  limit: number,
): Generator<string> {
  if (doc.items.length > limit) yield "items: more items than the page limit";
  if (doc.items.length > 0 && doc.offset + doc.items.length > doc.total) {
    yield "total: smaller than offset plus items on this page";
  }
  const keys = doc.items.map((i) => i.key);
  if (new Set(keys).size !== keys.length) yield "items: each result appears once";
  for (const [i, item] of doc.items.entries()) yield* searchResult(`items[${i}]`, item);
}

function* searchResults(doc: SearchResults): Generator<string> {
  yield* page(doc, doc.limit);
  for (const [i, item] of doc.items.entries()) {
    if (item.reasons !== undefined || item.item_id !== undefined) {
      yield `items[${i}]: only collection items carry reasons or item IDs`;
    }
  }
  for (const [name, facets] of Object.entries(doc.facets)) {
    const values = (facets as { value: string }[]).map((f) => f.value);
    if (new Set(values).size !== values.length) yield `facets.${name}: each value appears once`;
    for (const [j, facet] of (facets as { count: number }[]).entries()) {
      if (facet.count > doc.total) yield `facets.${name}[${j}].count: cannot exceed total`;
    }
  }
}

function* searchIndex(doc: SearchIndexStatus): Generator<string> {
  const reasons: string[] = doc.reasons;
  if ((doc.status === "current") !== (reasons.length === 0)) {
    yield "reasons: a current index has no reasons; any other status has one";
  }
  if ((doc.status === "corrupt") !== reasons.includes("full_text_corrupt")) {
    yield "status: corrupt exactly when the full-text index failed its check";
  }
  if (reasons.includes("full_text_corrupt") && !doc.checked) {
    yield "checked: corruption is only reported by a full check";
  }
  if ((doc.index_version !== doc.expected_version) !== reasons.includes("version_changed")) {
    yield "reasons: version_changed exactly when the index version differs";
  }
}

function* collection(doc: Collection): Generator<string> {
  yield* page(doc, 100);
  if (doc.kind === "manual" && doc.rule !== undefined) {
    yield "rule: only rule-based collections have a rule";
  }
  if (doc.kind === "rule" && doc.item_count !== undefined) {
    yield "item_count: rule-based collections have no stored items";
  }
  for (const [i, item] of doc.items.entries()) {
    if (doc.kind === "rule") {
      if (item.reasons === undefined) {
        yield `items[${i}].reasons: rule-based items explain why they matched`;
      }
      if (item.item_id !== undefined) {
        yield `items[${i}].item_id: rule-based collections have no stored items`;
      }
    } else {
      if (item.reasons !== undefined) yield `items[${i}].reasons: manual items were added by hand`;
      if (item.item_id === undefined || item.added_at === undefined) {
        yield `items[${i}]: manual items carry item_id and added_at`;
      }
    }
  }
  if (doc.kind === "manual" && doc.item_count !== doc.total) {
    yield "total: must equal item_count for a manual collection";
  }
}

const PATH_FORMATS = new Set(["project", "otio", "fcpxml"]);

function* exportResult(doc: ExportResult): Generator<string> {
  if ((doc.stability === "experimental") !== (doc.format === "fcpxml")) {
    yield "stability: FCPXML is experimental; every other format is stable";
  }
  if (doc.includes_paths && !PATH_FORMATS.has(doc.format)) {
    yield "includes_paths: only project, OTIO and FCPXML exports may carry paths";
  }
}

function* projectExport(doc: ProjectExport): Generator<string> {
  const known = new Set(doc.document.sources.map((s) => s.asset_id));
  const seen = new Set<string>();
  for (const [i, location] of (doc.source_locations ?? []).entries()) {
    if (!known.has(location.asset_id)) {
      yield `source_locations[${i}].asset_id: not a source of the document`;
    }
    if (seen.has(location.asset_id)) {
      yield `source_locations[${i}].asset_id: each source appears once`;
    }
    seen.add(location.asset_id);
  }
}

function* eventExport(doc: EventExportLine): Generator<string> {
  if (doc.record !== "event") return;
  yield* range("effective.end_ms", doc.effective.start_ms, doc.effective.end_ms);
  for (const [i, span] of (doc.project_ranges ?? []).entries()) {
    yield* range(`project_ranges[${i}].end_ms`, span.start_ms, span.end_ms, true);
  }
}

function* privacyReview(doc: PrivacyReview): Generator<string> {
  const ids = new Set<string>();
  for (const f of doc.flags) {
    yield* range("privacy.flag.end_ms", f.start_ms, f.end_ms, true);
    if (f.region) yield* region("privacy.flag.region", f.region);
    if (ids.has(f.id)) yield "privacy: duplicate finding";
    ids.add(f.id);
    const hasSource = [f.asset_id, f.source_start_ms, f.source_end_ms].filter(
      (v) => v !== undefined,
    ).length;
    if (hasSource !== 0 && hasSource !== 3) yield "privacy: source range requires all fields";
    if (f.source_start_ms !== undefined && f.source_end_ms !== undefined)
      yield* range("privacy.source_end_ms", f.source_start_ms, f.source_end_ms, true);
  }
  for (const r of doc.config.ranges)
    yield* range("privacy.spoiler.end_ms", r.start_ms, r.end_ms, true);
  if (doc.summary.token !== doc.token) yield "privacy: summary token differs";
  if (doc.summary.unresolved !== doc.flags.filter((f) => f.decision === "unresolved").length)
    yield "privacy: unresolved count differs";
  if (doc.current !== (doc.summary.acknowledged && doc.summary.unresolved === 0))
    yield "privacy: gate state differs";
  if (
    doc.summary.findings.length !== doc.flags.length ||
    doc.flags.some((f, i) => {
      const d = doc.summary.findings[i];
      return !d || d.id !== f.id || d.category !== f.category || d.state !== f.decision;
    })
  )
    yield "privacy: summary decisions differ";
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- each rule narrows its own input
const RULES: Record<string, (doc: any) => Iterable<string>> = {
  "diagnostics-report": diagnosticsReport,
  "platform-capabilities": platformCapabilities,
  "model-manager": modelManager,
  "system-doctor": systemDoctor,
  "privacy-review": privacyReview,
  "event-export": eventExport,
  "export-result": exportResult,
  "project-export": projectExport,
  collection,
  search: searchResults,
  "search-index": searchIndex,
  "story-candidate": storyCandidate,
  "story-candidates": storyCandidates,
  evaluation,
  "evaluation-observations": evaluation,
  "event-review": eventReview,
  transcript,
  transcription,
  "speech-models": speechModels,
  render: renderRecord,
  "render-encoders": renderEncoders,
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
  "editor-project": editorProject,
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
