// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { EditorProject, Segment } from "@openworld-moments/contracts";
import type { EditorCommand } from "./editor";
import { audioAt, type AudioOperation } from "./editorAudio";
export function AudioPanel({
  document,
  cut,
  atMs,
  onCommand,
}: {
  document: EditorProject;
  cut: Segment | undefined;
  atMs: number;
  onCommand: (c: EditorCommand) => void;
}) {
  const audio = document.project.audio;
  const [projectGain, setProjectGain] = useState<{ audio: typeof audio; value: string }>();
  const [gain, setGain] = useState("0"),
    [start, setStart] = useState("0"),
    [end, setEnd] = useState("1000");
  const current = audioAt(audio, atMs);
  const command = (operation: AudioOperation) => onCommand({ kind: "audio", operation });
  const range = { start_ms: Number(start), end_ms: Number(end) };
  const selected = cut
    ? {
        start_ms: cut.timeline_start_ms,
        end_ms: cut.timeline_start_ms + cut.source_out_ms - cut.source_in_ms,
      }
    : undefined;
  return (
    <section className="panel audio-panel" aria-labelledby="audio-heading">
      <h2 id="audio-heading">Audio</h2>
      <p className="notice-box">
        Mixed console audio cannot be separated here. Muting affects gameplay, music and voice chat
        together. Preview uses the first audio stream; it does not isolate voice chat or music.
      </p>
      <output aria-label="Audio at playhead">
        {current.muted ? "Muted" : `${current.gainDb} dB`}
      </output>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          command({
            action: "project-gain",
            gain_db: Number(projectGain?.audio === audio ? projectGain.value : audio.gain_db),
          });
        }}
      >
        <label>
          Project gain (dB)
          <input
            type="number"
            min={-60}
            max={24}
            step={0.5}
            required
            value={projectGain?.audio === audio ? projectGain.value : String(audio.gain_db)}
            onChange={(e) => setProjectGain({ audio, value: e.target.value })}
          />
        </label>
        <button>Apply project gain</button>
      </form>
      <p className="muted">
        0 dB is unchanged; +6 dB is approximately twice the amplitude and may clip. Range gain
        replaces project gain inside its range. Mute takes precedence.
      </p>
      <div className="row">
        <label>
          Cut / range gain (dB)
          <input
            type="number"
            min={-60}
            max={24}
            step={0.5}
            required
            value={gain}
            onChange={(e) => setGain(e.target.value)}
          />
        </label>
        <button
          disabled={!selected}
          onClick={() => {
            if (selected)
              command({
                action: "range-gain",
                ...selected,
                gain_db: gain.trim() ? Number(gain) : NaN,
              });
          }}
        >
          Apply gain to selected cut
        </button>
        <button
          disabled={!selected}
          onClick={() => {
            if (selected) command({ action: "clear-gain", ...selected });
          }}
        >
          Use project gain for selected cut
        </button>
      </div>
      <div className="row">
        <button
          disabled={!selected}
          onClick={() => {
            if (selected) command({ action: "mute", ...selected });
          }}
        >
          Mute selected cut
        </button>
        <button
          disabled={!selected}
          onClick={() => {
            if (selected) command({ action: "unmute", ...selected });
          }}
        >
          Unmute selected cut
        </button>
      </div>
      <form onSubmit={(e) => e.preventDefault()}>
        <div className="row">
          <label>
            Audio range in (ms)
            <input
              type="number"
              min={0}
              step={1}
              required
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            Audio range out (ms)
            <input
              type="number"
              min={1}
              step={1}
              required
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <button type="button" onClick={() => setStart(String(Math.round(atMs)))}>
            Use playhead for audio in
          </button>
          <button type="button" onClick={() => setEnd(String(Math.round(atMs)))}>
            Use playhead for audio out
          </button>
        </div>
        <div className="row">
          <button
            onClick={(e) => {
              if (e.currentTarget.form?.reportValidity()) command({ action: "mute", ...range });
            }}
          >
            Mute audio range
          </button>
          <button
            onClick={(e) => {
              if (e.currentTarget.form?.reportValidity()) command({ action: "unmute", ...range });
            }}
          >
            Unmute audio range
          </button>
          <button
            onClick={(e) => {
              if (e.currentTarget.form?.reportValidity())
                command({
                  action: "range-gain",
                  ...range,
                  gain_db: gain.trim() ? Number(gain) : NaN,
                });
            }}
          >
            Apply gain to audio range
          </button>
        </div>
      </form>
      <ul aria-label="Muted ranges">
        {audio.mute_ranges.map((r, i) => (
          <li key={i}>
            {r.start_ms}–{r.end_ms} ms{" "}
            <button onClick={() => command({ action: "unmute", ...r })}>Remove mute {i + 1}</button>
          </li>
        ))}
      </ul>
      <ul aria-label="Gain ranges">
        {audio.gain_ranges?.map((r, i) => (
          <li key={i}>
            {r.start_ms}–{r.end_ms} ms · {r.gain_db} dB{" "}
            <button onClick={() => command({ action: "clear-gain", ...r })}>
              Remove gain {i + 1}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
