// SPDX-License-Identifier: AGPL-3.0-or-later
import { blurRegionAt } from "./privacyBlur";
import { useState } from "react";
import type {
  BlurOverlay,
  PrivacyReview,
  PrivacyConfig,
  PrivacyDecision,
} from "@openworld-moments/contracts";
import {
  privacyReview,
  configurePrivacy,
  decidePrivacy,
  clearPrivacy,
  deletePrivacyText,
  describeError,
} from "./api";
import { useAction, useQuery } from "./query";
import type { ProjectWorkspace } from "./projectWorkspace";
import type { EditorCommand } from "./editor";
import { formatClock } from "./SessionView";

function Checklist({
  report,
  disabled,
  onSave,
  seek,
  onCommand,
}: {
  report: PrivacyReview;
  disabled: boolean;
  onSave: (d: PrivacyDecision[], a: boolean) => Promise<void>;
  seek: (ms: number) => void;
  onCommand: (c: EditorCommand) => void;
}) {
  const [decisions, setDecisions] = useState<PrivacyDecision[]>(
    report.flags.map((f) => ({ id: f.id, state: f.decision })),
  );
  const [ack, setAck] = useState(report.summary.acknowledged);
  const save = useAction(async () => onSave(decisions, ack));
  return (
    <div>
      <p role="status">
        {report.current ? "Review recorded for this saved revision." : "Export review is required."}{" "}
        {report.flags.length} findings. Scores are heuristic, not probabilities.
      </p>
      <fieldset className="privacy-checklist" disabled={disabled}>
        <legend>Review choices for saved revision {report.revision}</legend>
        <ol className="privacy-findings" aria-label="Privacy findings">
          {report.flags.map((f) => (
            <li key={f.id}>
              {f.time_domain === "session" && report.session_id ? (
                <a href={`#/session/${report.session_id}@${f.start_ms}`}>
                  Session {f.category} · {formatClock(f.start_ms)}–{formatClock(f.end_ms)} (outside
                  this cut)
                </a>
              ) : (
                <button onClick={() => seek(f.start_ms)}>
                  {f.category} · {formatClock(f.start_ms)}–{formatClock(f.end_ms)}
                </button>
              )}
              <p>
                {f.evidence_kind} · score {f.confidence.toFixed(2)} · {f.evidence}
              </p>
              {f.asset_id && (
                <p className="muted">
                  Source {f.asset_id} · {f.source_start_ms}–{f.source_end_ms} ms
                  {f.region ? ` · source ROI ${f.region.join(", ")}` : ""}
                </p>
              )}
              <label>
                Decision for {f.category} at {f.start_ms} ms{" "}
                <select
                  value={decisions.find((d) => d.id === f.id)?.state ?? "unresolved"}
                  onChange={(e) =>
                    setDecisions((ds) =>
                      ds.map((d) =>
                        d.id === f.id
                          ? { ...d, state: e.target.value as PrivacyDecision["state"] }
                          : d,
                      ),
                    )
                  }
                >
                  <option value="unresolved">Unresolved / restore finding</option>
                  <option value="acknowledge">Acknowledge risk</option>
                  <option value="ignore">Ignore / false positive</option>
                  <option value="fixed">I manually fixed and checked this</option>
                </select>
              </label>
              {f.time_domain !== "session" &&
                (f.evidence_kind === "transcript" ||
                  f.evidence_kind === "audio" ||
                  f.category === "mixed_audio") && (
                  <button
                    onClick={() =>
                      onCommand({
                        kind: "audio",
                        operation: { action: "mute", start_ms: f.start_ms, end_ms: f.end_ms },
                      })
                    }
                  >
                    Mute this range
                  </button>
                )}
            </li>
          ))}
        </ol>
        <label className="check">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I
          reviewed this project, voice-chat consent, spoilers and publishing rights. Detection can
          miss risks; this is not privacy or legal clearance.
        </label>
        <button disabled={save.busy} onClick={() => void save.run()}>
          Save review decisions
        </button>
        {save.error && <p role="alert">{describeError(save.error)}</p>}
      </fieldset>
    </div>
  );
}
function Spoilers({
  config,
  onSave,
}: {
  config: PrivacyConfig;
  onSave: (c: PrivacyConfig) => Promise<void>;
}) {
  const [labels, setLabels] = useState(config.labels.join("\n"));
  const [ranges, setRanges] = useState(config.ranges);
  const [start, setStart] = useState(0),
    [end, setEnd] = useState(1000),
    [label, setLabel] = useState("");
  const save = useAction(async () =>
    onSave({
      labels: labels
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      ranges,
    }),
  );
  return (
    <details>
      <summary>Spoiler labels and ranges</summary>
      <label>
        Spoiler labels (one per line)
        <textarea value={labels} onChange={(e) => setLabels(e.target.value)} />
      </label>
      <p>
        Literal words or phrases only. Nothing is censored automatically. Ranges use project
        milliseconds; check them again after timeline edits.
      </p>
      <label>
        Spoiler range start (ms)
        <input
          type="number"
          min={0}
          step={1}
          value={start}
          onChange={(e) => setStart(Number(e.target.value))}
        />
      </label>
      <label>
        Spoiler range end (ms)
        <input
          type="number"
          min={1}
          step={1}
          value={end}
          onChange={(e) => setEnd(Number(e.target.value))}
        />
      </label>
      <label>
        Spoiler range label
        <input maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <button
        disabled={!label.trim() || end <= start}
        onClick={() => setRanges((rs) => [...rs, { start_ms: start, end_ms: end, label }])}
      >
        Add spoiler range to draft
      </button>
      <ul>
        {ranges.map((r, i) => (
          <li key={i}>
            {r.label}: {r.start_ms}–{r.end_ms} ms{" "}
            <button onClick={() => setRanges((rs) => rs.filter((_, n) => n !== i))}>
              Remove spoiler range {i + 1}
            </button>
          </li>
        ))}
      </ul>
      <button disabled={save.busy} onClick={() => void save.run()}>
        Save spoiler configuration
      </button>
      {save.error && <p role="alert">{describeError(save.error)}</p>}
    </details>
  );
}
function BlurEditor({
  blurs,
  duration,
  atMs,
  onSave,
  seek,
}: {
  blurs: BlurOverlay[];
  duration: number;
  atMs: number;
  onSave: (b: BlurOverlay[]) => void;
  seek: (ms: number) => void;
}) {
  const [draft, setDraft] = useState<BlurOverlay[]>(structuredClone(blurs)),
    [selected, setSelected] = useState(0);
  const current = draft[selected];
  const edit = (change: (b: BlurOverlay) => BlurOverlay) =>
    setDraft((ds) => ds.map((b, i) => (i === selected ? change(b) : b)));
  const save = useAction(async () => onSave(draft));
  const regionField = (axis: number, value: number) =>
    edit((b) => {
      const region = [...b.region] as BlurOverlay["region"];
      region[axis] = value;
      return {
        ...b,
        region,
        keyframes: b.keyframes?.map((k, i) => ({
          ...k,
          region: k.region.map((v, n) =>
            n === axis && (axis >= 2 || i === 0) ? value : v,
          ) as BlurOverlay["region"],
        })),
      };
    });
  return (
    <details>
      <summary>Manual moving blur regions</summary>
      <p>
        Rectangles use output-frame coordinates from 0 to 1. Keyframes move linearly with fixed
        dimensions. These apply to every aspect ratio; verify each output. Blur appearance is
        approximate, and exported text remains readable.
      </p>
      <button
        onClick={() => {
          setSelected(draft.length);
          setDraft((ds) => [
            ...ds,
            {
              kind: "blur",
              start_ms: Math.min(atMs, Math.max(0, duration - 1)),
              end_ms: duration,
              region: [0.1, 0.1, 0.25, 0.15],
              keyframes: [{ at_ms: 0, region: [0.1, 0.1, 0.25, 0.15] }],
            },
          ]);
        }}
        disabled={duration <= 0}
      >
        Draft a blur at playhead
      </button>
      {current && (
        <fieldset>
          <legend>Blur region</legend>
          <label>
            Selected blur
            <select value={selected} onChange={(e) => setSelected(Number(e.target.value))}>
              {draft.map((_, i) => (
                <option key={i} value={i}>
                  Blur {i + 1}
                </option>
              ))}
            </select>
          </label>
          <label>
            Blur start (ms)
            <input
              type="number"
              step={1}
              value={current.start_ms}
              onChange={(e) => edit((b) => ({ ...b, start_ms: Number(e.target.value) }))}
            />
          </label>
          <label>
            Blur end (ms)
            <input
              type="number"
              step={1}
              value={current.end_ms}
              onChange={(e) => edit((b) => ({ ...b, end_ms: Number(e.target.value) }))}
            />
          </label>
          {["X", "Y", "Width", "Height"].map((name, i) => (
            <label key={name}>
              Blur {name}
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={current.region[i]}
                onChange={(e) => regionField(i, Number(e.target.value))}
              />
            </label>
          ))}
          <p>Keyframe times are relative to the blur start. The first keyframe starts at zero.</p>
          {(current.keyframes ?? [{ at_ms: 0, region: current.region }]).map((k, i) => (
            <fieldset key={i}>
              <legend>Blur keyframe {i + 1}</legend>
              <label>
                Keyframe {i + 1} time (ms)
                <input
                  type="number"
                  value={k.at_ms}
                  disabled={i === 0}
                  onChange={(e) =>
                    edit((b) => ({
                      ...b,
                      keyframes: (b.keyframes ?? [{ at_ms: 0, region: b.region }]).map((v, n) =>
                        n === i ? { ...v, at_ms: Number(e.target.value) } : v,
                      ),
                    }))
                  }
                />
              </label>
              {[0, 1].map((axis) => (
                <label key={axis}>
                  Keyframe {i + 1} {axis === 0 ? "X" : "Y"}
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={k.region[axis]}
                    onChange={(e) =>
                      edit((b) => {
                        const keys = structuredClone(
                          b.keyframes ?? [{ at_ms: 0, region: b.region }],
                        );
                        const key = keys[i];
                        if (key) key.region[axis] = Number(e.target.value);
                        return { ...b, keyframes: keys, region: keys[0]?.region ?? b.region };
                      })
                    }
                  />
                </label>
              ))}
              <button
                disabled={i === 0}
                onClick={() =>
                  edit((b) => ({ ...b, keyframes: b.keyframes?.filter((_, n) => n !== i) }))
                }
              >
                Remove keyframe {i + 1}
              </button>
            </fieldset>
          ))}
          <button
            onClick={() =>
              edit((b) => {
                const keys = structuredClone(b.keyframes ?? [{ at_ms: 0, region: b.region }]);
                const at = Math.max(1, Math.min(b.end_ms - b.start_ms - 1, atMs - b.start_ms));
                return {
                  ...b,
                  keyframes: [
                    ...keys.filter((k) => k.at_ms !== at),
                    { at_ms: at, region: blurRegionAt(b, b.start_ms + at) },
                  ].sort((a, b) => a.at_ms - b.at_ms),
                };
              })
            }
          >
            Add keyframe at playhead
          </button>
          <button onClick={() => seek(current.start_ms)}>Seek selected blur</button>
          <button
            onClick={() => {
              setDraft((ds) => ds.filter((_, i) => i !== selected));
              setSelected(0);
            }}
          >
            Remove selected blur from draft
          </button>
        </fieldset>
      )}
      <button disabled={save.busy} onClick={() => void save.run()}>
        Apply blur regions
      </button>
      {save.error && <p role="alert">{describeError(save.error)}</p>}
    </details>
  );
}
export function PrivacyPanel({
  workspace,
  atMs,
  onCommand,
  seek,
}: {
  workspace: ProjectWorkspace;
  atMs: number;
  onCommand: (c: EditorCommand) => void;
  seek: (ms: number) => void;
}) {
  const doc = workspace.document,
    pid = doc.project.id;
  const [refresh, setRefresh] = useState(0);
  const key = `privacy:${pid}:${workspace.autosave.revision}:${refresh}`;
  const report = useQuery(key, () => privacyReview(pid));
  const update = async (action: () => Promise<unknown>) => {
    await workspace.flush();
    await action();
    setRefresh((n) => n + 1);
  };
  const scan = useAction(async () => {
    await workspace.flush();
    setRefresh((n) => n + 1);
  });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const clear = useAction(async () => update(() => clearPrivacy(pid)));
  const purge = useAction(async () => {
    await workspace.flush();
    await deletePrivacyText(pid);
    window.location.reload();
  });
  const duration = doc.project.tracks
    .flatMap((t) => t.segments)
    .reduce((n, c) => n + c.source_out_ms - c.source_in_ms, 0);
  return (
    <section className="panel privacy-review" aria-labelledby="privacy-heading">
      <h2 id="privacy-heading">Privacy and spoiler review</h2>
      <p>
        Local checks surface possible phone numbers, explicit usernames, subtitles, speech and
        spoilers. No identity recognition or guaranteed detection. Mixed voice chat cannot be
        separated. Findings never censor footage automatically.
      </p>
      <button disabled={scan.busy} onClick={() => void scan.run()}>
        Scan saved project / refresh review
      </button>
      {workspace.status !== "saved" && (
        <p role="status">Save and refresh to review the current edits.</p>
      )}
      {report.data && (
        <>
          <Spoilers
            key={JSON.stringify(report.data.config)}
            config={report.data.config}
            onSave={async (c) => update(() => configurePrivacy(pid, c))}
          />
          <Checklist
            key={report.data.token + JSON.stringify(report.data.summary)}
            report={report.data}
            disabled={
              workspace.status !== "saved" ||
              report.loading ||
              report.data.revision !== workspace.autosave.revision
            }
            seek={seek}
            onCommand={onCommand}
            onSave={async (d, a) =>
              update(() => decidePrivacy(pid, report.data?.token ?? "", d, a))
            }
          />
        </>
      )}
      <BlurEditor
        key={JSON.stringify(doc.project.overlays)}
        blurs={doc.project.overlays.filter((o): o is BlurOverlay => o.kind === "blur")}
        duration={duration}
        atMs={atMs}
        seek={seek}
        onSave={(b) =>
          onCommand({
            kind: "settings",
            overlays: [...doc.project.overlays.filter((o) => o.kind !== "blur"), ...b],
          })
        }
      />
      <details>
        <summary>Delete local review data and derived text</summary>
        <p>
          Review findings are computed in memory. Saved choices and spoiler configuration stay in
          this library until deleted. Deleting derived text removes this session's OCR/transcripts
          and historical text evidence, and this project's captions, text overlays and recovery
          copy. Other projects, exported files and library backups may retain copies; delete those
          separately. Sources and playback copies are preserved. Cancel analysis/transcription jobs
          first.
        </p>
        <button disabled={clear.busy} onClick={() => void clear.run()}>
          Delete review decisions and spoiler configuration
        </button>
        <label className="check">
          <input
            type="checkbox"
            checked={confirmDelete}
            onChange={(e) => setConfirmDelete(e.target.checked)}
          />
          Delete the described derived text and reload, clearing this window's undo history
        </label>
        <button disabled={!confirmDelete || purge.busy} onClick={() => void purge.run()}>
          Delete derived text
        </button>
      </details>
      {(report.error ?? scan.error ?? clear.error ?? purge.error) && (
        <p role="alert">
          {describeError(
            (report.error ?? scan.error ?? clear.error ?? purge.error) as import("./api").ApiError,
          )}
        </p>
      )}
    </section>
  );
}
