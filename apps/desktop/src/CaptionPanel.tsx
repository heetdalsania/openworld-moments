// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import type { Caption, CaptionSettings, EditorProject } from "@openworld-moments/contracts";
import {
  describeError,
  exportCaptions,
  getCalibration,
  getTranscript,
  listProfiles,
  toApiError,
} from "./api";
import {
  captionConflicts,
  captionsFromTranscript,
  DEFAULT_CAPTIONS,
  serializeCaptions,
} from "./captions";
import type { EditorCommand } from "./editor";
import type { ProjectWorkspace } from "./projectWorkspace";
import { useQuery } from "./query";

export function CaptionPreview({ document, atMs }: { document: EditorProject; atMs: number }) {
  const settings = document.project.caption_settings ?? DEFAULT_CAPTIONS;
  const cues = document.project.captions.filter((c) => c.start_ms <= atMs && atMs < c.end_ms);
  const [x, y, w, h] = settings.region;
  return (
    <div
      className={`caption-safe-area ${settings.preset}`}
      role="group"
      aria-label="Caption safe area"
      style={{
        left: `${x * 100}%`,
        top: `${y * 100}%`,
        width: `${w * 100}%`,
        height: `${h * 100}%`,
      }}
    >
      {cues.length > 0 ? (
        <div className="caption-preview-text" aria-label="Caption preview">
          {cues.map((c, i) => (
            <span key={i}>{c.text}</span>
          ))}
        </div>
      ) : (
        <span className="caption-guide">Caption safe area</span>
      )}
    </div>
  );
}
function CueForm({
  cue,
  index,
  count,
  onCommand,
  seek,
}: {
  cue: Caption;
  index: number;
  count: number;
  onCommand: (c: EditorCommand) => void;
  seek: (n: number) => void;
}) {
  const signature = JSON.stringify(cue);
  const initial = {
    signature,
    start: String(cue.start_ms),
    end: String(cue.end_ms),
    text: cue.text,
  };
  const [current, setDraft] = useState(initial);
  if (current.signature !== signature) setDraft(initial);
  const update = (patch: Partial<typeof current>) => setDraft({ ...current, ...patch });
  const initialSplit = {
    signature,
    at: String(Math.floor((cue.start_ms + cue.end_ms) / 2)),
    character: String(Math.max(1, Math.floor([...cue.text].length / 2))),
  };
  const [division, setSplit] = useState(initialSplit);
  if (division.signature !== signature) setSplit(initialSplit);
  return (
    <div className="caption-inspector">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onCommand({
            kind: "captions",
            operation: {
              action: "update",
              index,
              cue: {
                start_ms: Number(current.start),
                end_ms: Number(current.end),
                text: current.text,
              },
            },
          });
        }}
      >
        <label>
          Caption text
          <textarea
            required
            maxLength={1000}
            rows={3}
            value={current.text}
            onChange={(e) => update({ text: e.target.value })}
          />
        </label>
        <div className="row">
          <label>
            Caption in (ms)
            <input
              type="number"
              min={0}
              step={1}
              required
              value={current.start}
              onChange={(e) => update({ start: e.target.value })}
            />
          </label>
          <label>
            Caption out (ms)
            <input
              type="number"
              min={1}
              step={1}
              required
              value={current.end}
              onChange={(e) => update({ end: e.target.value })}
            />
          </label>
        </div>
        <button type="submit" className="primary">
          Apply caption
        </button>
        <button type="button" onClick={() => setDraft(initial)}>
          Reset caption fields
        </button>
      </form>
      <div className="row">
        <button onClick={() => seek(cue.start_ms)}>Preview selected caption</button>
        <button
          onClick={() => onCommand({ kind: "captions", operation: { action: "remove", index } })}
        >
          Remove caption
        </button>
        <button
          disabled={index >= count - 1}
          onClick={() => onCommand({ kind: "captions", operation: { action: "merge", index } })}
        >
          Merge with next caption
        </button>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const chars = [...cue.text],
            at = Number(division.character);
          if (!Number.isInteger(at) || at < 1 || at >= chars.length) return;
          onCommand({
            kind: "captions",
            operation: {
              action: "split",
              index,
              at_ms: Number(division.at),
              left: chars.slice(0, at).join(""),
              right: chars.slice(at).join(""),
            },
          });
        }}
      >
        <div className="row">
          <label>
            Caption split time (ms)
            <input
              type="number"
              min={cue.start_ms + 1}
              max={cue.end_ms - 1}
              step={1}
              required
              value={division.at}
              onChange={(e) => setSplit({ ...division, at: e.target.value })}
            />
          </label>
          <label>
            Split text after character
            <input
              type="number"
              min={1}
              max={[...cue.text].length - 1}
              step={1}
              required
              value={division.character}
              onChange={(e) => setSplit({ ...division, character: e.target.value })}
            />
          </label>
          <button disabled={cue.end_ms - cue.start_ms < 2 || [...cue.text].length < 2}>
            Split caption
          </button>
        </div>
        <p className="muted">
          Splits the saved text at a Unicode character boundary. Apply text changes first.
        </p>
      </form>
    </div>
  );
}

export function CaptionPanel({
  workspace,
  atMs,
  sourceAspect,
  onCommand,
  seek,
}: {
  workspace: ProjectWorkspace;
  atMs: number;
  sourceAspect: number;
  onCommand: (c: EditorCommand) => void;
  seek: (n: number) => void;
}) {
  const document = workspace.document,
    project = document.project;
  const settings = project.caption_settings ?? DEFAULT_CAPTIONS;
  const [selected, setSelected] = useState(0),
    [newText, setNewText] = useState("");
  const [mode, setMode] = useState<"segments" | "words">("segments"),
    [replace, setReplace] = useState(false),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const request = useRef(0);
  useEffect(
    () => () => {
      request.current++;
    },
    [],
  );
  const profiles = useQuery("profiles", listProfiles);
  const profile = useQuery(
    document.layout.profile_id ? `calibration:${document.layout.profile_id}` : null,
    () => getCalibration(document.layout.profile_id ?? ""),
  );
  const configured = profile.data?.effective;
  const [fw, fh] = document.layout.aspect_ratio.split(":").map(Number);
  const frameAspect = (fw ?? 16) / (fh ?? 9);
  const conflicts = configured
    ? captionConflicts(settings, configured, sourceAspect, frameAspect)
    : [];
  const placement =
    (
      [
        ["top", 0.06],
        ["middle", 0.45],
        ["bottom", 0.76],
      ] as const
    ).find(
      ([, y]) =>
        settings.region[0] === 0.08 &&
        settings.region[1] === y &&
        settings.region[2] === 0.84 &&
        settings.region[3] === 0.18,
    )?.[0] ?? "custom";
  const change = (patch: Partial<CaptionSettings>) =>
    onCommand({ kind: "caption-settings", settings: { ...settings, ...patch } });
  const initialize = async () => {
    if (!project.session_id) return;
    const token = ++request.current,
      snapshot = workspace.document;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const transcript = await getTranscript(project.session_id);
      if (token !== request.current) return;
      if (workspace.document !== snapshot)
        throw new Error(
          "The project changed while loading the transcript. Your edits are kept; try again.",
        );
      const cues = captionsFromTranscript(snapshot, transcript, mode);
      if (!cues.length)
        throw new Error(
          "No transcript text intersects these cuts. Transcribe the session or add captions manually.",
        );
      workspace.execute({ kind: "captions", operation: { action: "replace", cues } });
      setSelected(0);
      setReplace(false);
      setMessage(`Added ${cues.length} editable captions. Review timing and text before export.`);
    } catch (e) {
      if (token === request.current) setError(describeError(toApiError(e)));
    } finally {
      if (token === request.current) setBusy(false);
    }
  };
  const exportSidecar = async (format: "srt" | "vtt") => {
    setError("");
    setMessage("");
    try {
      const text = serializeCaptions(project.captions, format);
      const saved = await exportCaptions(text, format);
      setMessage(
        saved
          ? `Saved ${format.toUpperCase()} sidecar.`
          : "Sidecar save cancelled. Your project is unchanged.",
      );
    } catch (e) {
      setError(describeError(toApiError(e)));
    }
  };
  const cue = project.captions[Math.min(selected, project.captions.length - 1)];
  return (
    <section
      className="panel caption-panel"
      aria-labelledby="captions-heading"
      onInputCapture={() => {
        if (busy) {
          request.current++;
          setBusy(false);
          setMessage("Transcript loading cancelled because fields changed. Your input is kept.");
        }
      }}
    >
      <div className="view-head">
        <h2 id="captions-heading">Captions</h2>
        <span>{project.captions.length} cues</span>
      </div>
      <p className="muted">
        Editable local text. Imported captions are a copy; deleting a session transcript does not
        delete copies saved in projects. Review automatic text and timing.
      </p>
      <div className="row">
        <label>
          Transcript timing
          <select value={mode} onChange={(e) => setMode(e.target.value as "segments" | "words")}>
            <option value="segments">Segment timing</option>
            <option value="words">Word timing</option>
          </select>
        </label>
        {project.captions.length > 0 && (
          <label className="check">
            <input
              type="checkbox"
              checked={replace}
              onChange={(e) => setReplace(e.target.checked)}
            />
            Replace existing captions
          </label>
        )}
        <button
          disabled={!project.session_id || busy || (project.captions.length > 0 && !replace)}
          onClick={() => void initialize()}
        >
          Use session transcript
        </button>
        {busy && (
          <button
            onClick={() => {
              request.current++;
              setBusy(false);
              setMessage("Transcript loading cancelled. Captions unchanged.");
            }}
          >
            Cancel transcript loading
          </button>
        )}
      </div>
      {!project.session_id && (
        <p className="muted">This project has no session transcript. Add captions manually.</p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onCommand({
            kind: "captions",
            operation: {
              action: "add",
              cue: {
                start_ms: Math.round(atMs),
                end_ms: Math.min(
                  Math.round(atMs) + 2000,
                  project.tracks[0]?.segments.reduce(
                    (n, s) => n + s.source_out_ms - s.source_in_ms,
                    0,
                  ) ?? 0,
                ),
                text: newText,
              },
            },
          });
        }}
      >
        <label>
          New caption text
          <input
            required
            maxLength={1000}
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
          />
        </label>
        <button>Add caption at playhead</button>
      </form>
      <div className="caption-cue-track" role="group" aria-label="Caption timeline">
        {project.captions.slice(0, 200).map((c, i) => (
          <button
            key={i}
            title={c.text}
            aria-label={`Preview caption ${i + 1} at ${c.start_ms} milliseconds`}
            style={{
              left: `${(c.start_ms / Math.max(1, project.tracks[0]?.segments.reduce((n, s) => n + s.source_out_ms - s.source_in_ms, 0) ?? 0)) * 100}%`,
            }}
            onClick={() => {
              setSelected(i);
              seek(c.start_ms);
            }}
          >
            {i + 1}
          </button>
        ))}
      </div>
      {project.captions.length > 200 && (
        <p className="muted">
          First 200 markers shown. All cues are available in Selected caption.
        </p>
      )}
      {project.captions.length > 0 && (
        <>
          <label>
            Selected caption
            <select
              value={Math.min(selected, project.captions.length - 1)}
              onChange={(e) => setSelected(Number(e.target.value))}
            >
              {project.captions.map((c, i) => (
                <option key={i} value={i}>
                  {i + 1} · {c.start_ms}–{c.end_ms} ms · {c.text.slice(0, 60)}
                </option>
              ))}
            </select>
          </label>
          {cue && (
            <CueForm
              key={Math.min(selected, project.captions.length - 1)}
              cue={cue}
              index={Math.min(selected, project.captions.length - 1)}
              count={project.captions.length}
              onCommand={onCommand}
              seek={seek}
            />
          )}
        </>
      )}
      <div className="caption-options row">
        <label>
          Caption style
          <select
            value={settings.preset}
            onChange={(e) => change({ preset: e.target.value as CaptionSettings["preset"] })}
          >
            <option value="high-contrast">High contrast</option>
            <option value="compact">Compact</option>
          </select>
        </label>
        <label>
          Caption placement
          <select
            value={placement}
            onChange={(e) =>
              change({
                region: [
                  0.08,
                  e.target.value === "top" ? 0.06 : e.target.value === "middle" ? 0.45 : 0.76,
                  0.84,
                  0.18,
                ],
              })
            }
          >
            <option value="custom" disabled>
              Custom saved area
            </option>
            <option value="top">Top safe area</option>
            <option value="middle">Middle safe area</option>
            <option value="bottom">Bottom safe area</option>
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={settings.burn_in}
            onChange={(e) => change({ burn_in: e.target.checked })}
          />
          Burn captions into future renders
        </label>
        <label>
          Sidecar output
          <select
            value={settings.sidecar}
            onChange={(e) => change({ sidecar: e.target.value as CaptionSettings["sidecar"] })}
          >
            <option value="none">None</option>
            <option value="srt">SRT</option>
            <option value="vtt">VTT</option>
            <option value="both">SRT and VTT</option>
          </select>
        </label>
      </div>
      <label>
        Protected HUD/subtitle profile
        <select
          value={document.layout.profile_id ?? ""}
          onChange={(e) => {
            const chosen = profiles.data?.find((p) => p.id === e.target.value);
            onCommand({
              kind: "settings",
              layout: chosen
                ? {
                    ...document.layout,
                    profile_id: chosen.id,
                    profile_version: chosen.profile_version,
                  }
                : { aspect_ratio: document.layout.aspect_ratio },
            });
          }}
        >
          <option value="">No profile configured</option>
          {profiles.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
        </select>
      </label>
      {conflicts.length > 0 && (
        <p role="alert">
          Caption safe area overlaps protected regions: {conflicts.join(", ")}. Choose another
          placement before rendering.
        </p>
      )}
      {!configured && (
        <p role="status">
          Protected regions are not available. Caption placement has not been checked against a game
          HUD.
        </p>
      )}
      {profiles.error && (
        <p role="alert">
          Profile list unavailable.{" "}
          <button onClick={profiles.refetch}>Retry caption profiles</button>
        </p>
      )}
      {(profile.data?.conflict || profile.data?.base_changed) && (
        <p role="alert">
          Protected-region calibration needs review.{" "}
          <a href="#/calibration">Review calibration in Settings</a> before relying on these
          regions.
        </p>
      )}
      {profile.error && <button onClick={profile.refetch}>Retry protected regions</button>}
      {configured && configured.profile_version !== document.layout.profile_version && (
        <p role="alert">
          The configured profile version changed. Review and reselect the profile before rendering.
        </p>
      )}
      <p className="muted">
        The dashed area shows caption placement in the output frame. Preview shows captions even
        when burn-in is off; sidecars keep plain text and timing. Exports use the saved layout;
        unsupported burn-in requires explicit text omission.
      </p>
      <div className="row">
        {(settings.sidecar === "srt" || settings.sidecar === "both") && (
          <button disabled={!project.captions.length} onClick={() => void exportSidecar("srt")}>
            Save SRT sidecar…
          </button>
        )}
        {(settings.sidecar === "vtt" || settings.sidecar === "both") && (
          <button disabled={!project.captions.length} onClick={() => void exportSidecar("vtt")}>
            Save VTT sidecar…
          </button>
        )}
      </div>
      {busy && <p role="status">Loading local transcript…</p>}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
