// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { EditorProject, Segment, VerticalCrop } from "@openworld-moments/contracts";
import { getCalibration, listProfiles } from "./api";
import type { EditorCommand } from "./editor";
import { useQuery } from "./query";
import {
  FIT,
  compatibleProfile,
  layoutWarnings,
  regionAt,
  suggest,
  type Region,
} from "./verticalLayout";

export function useLayoutProfile(document: EditorProject) {
  const result = useQuery(
    document.layout.profile_id ? `calibration:${document.layout.profile_id}` : null,
    () => getCalibration(document.layout.profile_id ?? ""),
  );
  const s = result.data;
  const profile =
    s &&
    !s.base_changed &&
    !s.conflict &&
    s.effective.profile_version === document.layout.profile_version
      ? s.effective
      : undefined;
  return { profile, loading: result.loading, error: result.error, refresh: result.refetch };
}
export function LayoutPanel({
  document,
  cut,
  width,
  height,
  atMs,
  onCommand,
  seek,
}: {
  document: EditorProject;
  cut?: Segment;
  width: number;
  height: number;
  atMs: number;
  onCommand: (c: EditorCommand) => void;
  seek: (ms: number) => void;
}) {
  const profiles = useQuery("profiles", listProfiles),
    loaded = useLayoutProfile(document);
  const profile = compatibleProfile(loaded.profile, width, height);
  const layout = cut?.vertical_crop ?? FIT;
  const suggestion = suggest(width, height, profile);
  const signature = JSON.stringify([cut?.id, layout]);
  const initial = { signature, at: 0, region: regionAt(layout, 0) };
  const [draft, setDraft] = useState(initial);
  if (draft.signature !== signature) setDraft(initial);
  const offset = Math.max(
    0,
    Math.min(
      (cut?.source_out_ms ?? 1) - (cut?.source_in_ms ?? 0) - 1,
      Math.round(atMs - (cut?.timeline_start_ms ?? 0)),
    ),
  );
  const active = regionAt(layout, offset),
    warnings = layoutWarnings(
      layout,
      width,
      height,
      profile,
      document.project.overlays.filter(
        (o) =>
          o.kind === "blur" &&
          cut &&
          o.start_ms < cut.timeline_start_ms + cut.source_out_ms - cut.source_in_ms &&
          o.end_ms > cut.timeline_start_ms,
      ),
    );
  const [showZones, setShowZones] = useState(true);
  const save = (v: VerticalCrop) => {
    if (cut) onCommand({ kind: "vertical-crop", id: cut.id, layout: v });
  };
  const apply = (strategy: "fixed" | "keyed") => {
    const r = draft.region;
    let keys =
      strategy === "fixed"
        ? []
        : layout.keyframes
            .filter((k) => k.at_ms !== draft.at)
            .map((k) => ({
              ...k,
              region: [
                Math.min(k.region[0], 1 - r[2]),
                Math.min(k.region[1], 1 - r[3]),
                r[2],
                r[3],
              ] as Region,
            }));
    keys.push({ at_ms: strategy === "fixed" ? 0 : draft.at, region: r });
    if (!keys.some((k) => k.at_ms === 0)) keys.push({ at_ms: 0, region: r });
    keys = keys.sort((a, b) => a.at_ms - b.at_ms);
    const manual = { ...layout, strategy, keyframes: keys };
    delete manual.suggestion;
    save(manual);
  };
  return (
    <section className="panel layout-panel" aria-labelledby="layout-heading">
      <h2 id="layout-heading">Vertical layout</h2>
      <p className="muted">
        1080 × 1920 variant · horizontal crops stay separate. Fit keeps the complete frame. Keyed
        crops ease between positions, holding before the first and after the last key. Size applies
        to every key on this cut.
      </p>
      <label>
        Layout profile{" "}
        <select
          value={document.layout.profile_id ?? ""}
          onChange={(e) => {
            const p = profiles.data?.find((p) => p.id === e.target.value);
            onCommand({
              kind: "settings",
              layout: {
                aspect_ratio: document.layout.aspect_ratio,
                ...(p ? { profile_id: p.id, profile_version: p.profile_version } : {}),
              },
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
      {loaded.loading && <p role="status">Loading protected regions…</p>}
      {(loaded.error || profiles.error) && (
        <p role="alert">
          Profile unavailable. Manual layouts still work.{" "}
          <button
            onClick={() => {
              loaded.refresh();
              profiles.refetch();
            }}
          >
            Retry layout profile
          </button>
        </p>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={showZones}
          onChange={(e) => setShowZones(e.target.checked)}
        />
        Show protected regions
      </label>
      <svg
        className="crop-map"
        viewBox="0 0 1000 600"
        role="img"
        aria-label="Full source: shaded area is removed by the crop"
        onPointerDown={(e) => {
          const b = e.currentTarget.getBoundingClientRect();
          setDraft({
            ...draft,
            region: [
              Math.max(
                0,
                Math.min(1 - draft.region[2], (e.clientX - b.left) / b.width - draft.region[2] / 2),
              ),
              Math.max(
                0,
                Math.min(1 - draft.region[3], (e.clientY - b.top) / b.height - draft.region[3] / 2),
              ),
              draft.region[2],
              draft.region[3],
            ],
          });
          e.currentTarget.setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!e.buttons) return;
          const b = e.currentTarget.getBoundingClientRect();
          setDraft({
            ...draft,
            region: [
              Math.max(
                0,
                Math.min(1 - draft.region[2], (e.clientX - b.left) / b.width - draft.region[2] / 2),
              ),
              Math.max(
                0,
                Math.min(1 - draft.region[3], (e.clientY - b.top) / b.height - draft.region[3] / 2),
              ),
              draft.region[2],
              draft.region[3],
            ],
          });
        }}
      >
        <rect width={1000} height={600} fill="#090c12" />
        <rect
          x={active[0] * 1000}
          y={active[1] * 600}
          width={active[2] * 1000}
          height={active[3] * 600}
          fill="#263d56"
          stroke="#7fc5ff"
          strokeWidth={4}
        />
        {showZones &&
          (profile?.safe_zones?.preserve ?? []).map((n) => {
            const r = profile?.regions[n];
            if (!r) return null;
            return (
              <g key={n}>
                <rect
                  x={r[0] * 1000}
                  y={r[1] * 600}
                  width={r[2] * 1000}
                  height={r[3] * 600}
                  fill="none"
                  stroke="#ffcd69"
                  strokeWidth={3}
                />
                <text x={r[0] * 1000 + 5} y={r[1] * 600 + 20} fill="#ffcd69" fontSize={20}>
                  {n}
                </text>
              </g>
            );
          })}
        <rect
          x={draft.region[0] * 1000}
          y={draft.region[1] * 600}
          width={draft.region[2] * 1000}
          height={draft.region[3] * 600}
          fill="none"
          stroke="white"
          strokeDasharray="10 8"
          strokeWidth={3}
        />
      </svg>
      <p className="muted">
        Solid blue: retained source at the playhead; dark: removed. Dashed white: unapplied crop.
        Drag its center or use the numeric controls.
      </p>
      {warnings.length > 0 && (
        <ul aria-label="Layout warnings">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <div className="row">
        <button disabled={!cut} onClick={() => save({ ...FIT, background: layout.background })}>
          Fit complete frame
        </button>
        <button disabled={!cut} onClick={() => save(structuredClone(FIT))}>
          Reset vertical layout
        </button>
        <label>
          Background{" "}
          <select
            value={layout.background}
            disabled={!cut}
            onChange={(e) => save({ ...layout, background: e.target.value as "solid" | "blur" })}
          >
            <option value="solid">Solid black</option>
            <option value="blur">Blurred fill</option>
          </select>
        </label>
      </div>
      <p>
        Suggestion · {Math.round(suggestion.confidence * 100)}% confidence · {suggestion.version}:{" "}
        {suggestion.reason}
      </p>
      <button
        disabled={!cut || loaded.loading}
        onClick={() =>
          save({
            ...suggestion.layout,
            background: layout.background,
            suggestion: {
              algorithm: "static-profile/1",
              confidence: suggestion.confidence,
              reason: suggestion.reason,
              ...(profile
                ? { profile_id: profile.id, profile_version: profile.profile_version }
                : {}),
            },
          })
        }
      >
        Use framing suggestion
      </button>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          apply("keyed");
        }}
      >
        <div className="row">
          <label>
            Key time in cut (ms)
            <input
              type="number"
              required
              min={0}
              max={Math.max(0, (cut?.source_out_ms ?? 1) - (cut?.source_in_ms ?? 0) - 1)}
              step={1}
              value={draft.at}
              onChange={(e) => setDraft({ ...draft, at: Number(e.target.value) })}
            />
          </label>
          <button
            type="button"
            disabled={!cut}
            onClick={() => setDraft({ ...draft, at: offset, region: regionAt(layout, offset) })}
          >
            Use playhead crop
          </button>
        </div>
        <div className="row">
          {(["Crop left", "Crop top", "Crop width", "Crop height"] as const).map((label, i) => (
            <label key={label}>
              {label}
              <input
                type="number"
                required
                step="any"
                min={i < 2 ? 0 : 0.001}
                max={
                  i === 0
                    ? 1 - draft.region[2]
                    : i === 1
                      ? 1 - draft.region[3]
                      : i === 2
                        ? 1 - draft.region[0]
                        : 1 - draft.region[1]
                }
                value={draft.region[i]}
                onChange={(e) => {
                  const r = [...draft.region] as Region;
                  r[i] = Number(e.target.value);
                  setDraft({ ...draft, region: r });
                }}
              />
            </label>
          ))}
        </div>
        <button type="submit" disabled={!cut}>
          Add or replace keyframe
        </button>
        <button
          type="button"
          disabled={!cut}
          onClick={(e) => {
            if (e.currentTarget.form?.reportValidity()) apply("fixed");
          }}
        >
          Apply fixed crop
        </button>
        <button
          type="button"
          onClick={() => {
            const cw = Math.min(1, 9 / 16 / (width / height)),
              ch = Math.min(1, 1 / (9 / 16 / (width / height)));
            setDraft({ ...draft, region: [(1 - cw) / 2, (1 - ch) / 2, cw, ch] });
          }}
        >
          Set 9:16 crop fields
        </button>
      </form>
      <ol aria-label="Crop keyframes">
        {layout.keyframes.map((k) => (
          <li key={k.at_ms}>
            {k.at_ms} ms · {k.region.map((n) => n.toFixed(3)).join(", ")}{" "}
            <button
              onClick={() => {
                setDraft({ ...draft, at: k.at_ms, region: [...k.region] });
                if (cut) seek(cut.timeline_start_ms + k.at_ms);
              }}
            >
              Edit keyframe {k.at_ms}
            </button>
            <button
              disabled={k.at_ms === 0}
              onClick={() =>
                save({ ...layout, keyframes: layout.keyframes.filter((x) => x.at_ms !== k.at_ms) })
              }
            >
              Remove keyframe {k.at_ms}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
