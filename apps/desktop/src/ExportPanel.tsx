// SPDX-License-Identifier: AGPL-3.0-or-later
// Export (M24): render the last saved project revision with a preset and an encoder
// that passed a real test encode. A hardware failure offers the CPU encoder as an
// explicit choice; text that cannot be drawn yet must be left out explicitly.
import { useState } from "react";
import { useLayoutProfile } from "./LayoutPanel";
import { compatibleProfile, FIT, layoutWarnings } from "./verticalLayout";
import type { ProjectMedia } from "./projectMedia";
import {
  describeError,
  type Job,
  projectRenders,
  type RenderRecord,
  renderEncoders,
  renderPresets,
  renderProject,
  toApiError,
} from "./api";
import type { EditorProject } from "@openworld-moments/contracts";
import { isActive, upsertJob, useJobs } from "./jobs";
import { formatDuration } from "./media";
import { useAction, useQuery } from "./query";

function forProject(job: Job, projectId: string): boolean {
  return (
    job.kind === "render" &&
    (job.params as { project_id?: string } | undefined)?.project_id === projectId
  );
}

function percent(job: Job): number | null {
  const p = job.progress;
  return p && p.total > 0 ? Math.round((p.done / p.total) * 100) : null;
}

function megabytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

/** Text the renderer cannot draw yet (drawing text is a hook in M24). */
export function textNeedingOmission(document: EditorProject): string[] {
  const project = document.project;
  const parts: string[] = [];
  if ((project.overlays ?? []).some((o) => o.kind === "text")) parts.push("text overlays");
  if (project.caption_settings?.burn_in && (project.captions ?? []).length > 0) {
    parts.push("burned-in captions");
  }
  return parts;
}

function RenderRow({
  record,
  onFallback,
  busy,
}: {
  record: RenderRecord;
  onFallback: (record: RenderRecord) => void;
  busy: boolean;
}) {
  const checks = record.validation?.checks ?? [];
  return (
    <li className="render-row">
      <div>
        <strong>
          {record.status === "ready"
            ? "Ready"
            : record.status === "failed"
              ? "Failed"
              : record.status === "cancelled"
                ? "Cancelled"
                : "Rendering"}
        </strong>{" "}
        · {record.preset_id} · {record.encoder}
        {record.project_revision !== undefined ? ` · revision ${record.project_revision}` : ""}
      </div>
      {record.output && (
        <p className="muted">
          {formatDuration(record.output.duration_ms)} · {megabytes(record.output.size_bytes)} ·{" "}
          {checks.filter((c) => c.passed).length}/{checks.length} checks passed. Saved in your
          library as <code>{record.output.relative_path}</code>.
        </p>
      )}
      {record.plan && record.plan.notes.length > 0 && (
        <ul className="muted">
          {record.plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      {record.error && record.status !== "cancelled" && <p role="alert">{record.error.message}</p>}
      {record.status === "failed" && record.validation && !record.validation.passed && (
        <ul className="muted" aria-label="Failed checks">
          {record.validation.checks
            .filter((c) => !c.passed)
            .map((c) => (
              <li key={c.name}>
                {c.name}: {c.detail}
              </li>
            ))}
        </ul>
      )}
      {record.fallback && (
        <button type="button" disabled={busy} onClick={() => onFallback(record)}>
          Render with the CPU encoder instead
        </button>
      )}
    </li>
  );
}

export function ExportPanel({
  projectId,
  document,
  flush,
  workerReady,
  media,
}: {
  projectId: string;
  document: EditorProject;
  flush: () => Promise<void> | Promise<number>;
  workerReady: boolean;
  media?: Record<string, ProjectMedia>;
}) {
  const presets = useQuery("render:presets", renderPresets);
  const encoders = useQuery("render:encoders", renderEncoders);
  const renders = useQuery(`renders:${projectId}`, () => projectRenders(projectId));
  const { jobs } = useJobs();
  const running = jobs.find((j) => forProject(j, projectId) && isActive(j));
  const [presetId, setPresetId] = useState<string | null>(null);
  const [encoderId, setEncoderId] = useState("libx264");
  const [omitText, setOmitText] = useState(false);
  const preset = presetId ?? presets.data?.[0]?.id ?? "";
  const selectedPreset = presets.data?.find((p) => p.id === preset);
  const vertical = Boolean(selectedPreset && selectedPreset.height > selectedPreset.width);
  const loadedProfile = useLayoutProfile(document);
  const layoutWarningsForProject = vertical
    ? (document.project.tracks[0]?.segments ?? []).flatMap((cut, i) => {
        const v = media?.[cut.asset_id]?.asset?.video;
        const [w, h]: [number, number] = v
          ? v.rotation === 90 || v.rotation === 270
            ? [v.height, v.width]
            : [v.width, v.height]
          : [1920, 1080];
        return layoutWarnings(
          cut.vertical_crop ?? FIT,
          w,
          h,
          compatibleProfile(loadedProfile.profile, w, h),
          document.project.overlays.filter(
            (o) =>
              o.kind === "blur" &&
              o.start_ms < cut.timeline_start_ms + cut.source_out_ms - cut.source_in_ms &&
              o.end_ms > cut.timeline_start_ms,
          ),
        ).map((w) => `Cut ${i + 1}: ${w}`);
      })
    : [];
  const reviewSignature = JSON.stringify([document, preset, loadedProfile.profile]);
  const [reviewed, setReviewed] = useState("");
  const reviewLayout = reviewed === reviewSignature;
  const encoder = encoders.data?.encoders.find((e) => e.id === encoderId);
  const text = textNeedingOmission(document);
  const start = useAction(async (encoderChoice: string) => {
    // Render exactly what is saved: write pending edits first.
    const revision = await flush();
    upsertJob(
      await renderProject(projectId, {
        preset_id: preset,
        ...(typeof revision === "number" ? { expected_revision: revision } : {}),
        encoder: encoderChoice,
        ...(text.length ? { omit_text: omitText } : {}),
        ...(vertical ? { review_layout: reviewLayout } : {}),
      }),
    );
  });
  const blocked =
    !workerReady || !preset || (text.length > 0 && !omitText) || (vertical && !reviewLayout);

  return (
    <section className="panel export" aria-labelledby="export-heading">
      <h2 id="export-heading">Export</h2>
      <p className="muted">
        Renders the last saved revision to an H.264/AAC MP4 inside your library. Originals are only
        read, never changed, and every render is checked before it is marked ready.
      </p>
      {(presets.error ?? encoders.error) && (
        <p role="alert">
          Export options could not be loaded:{" "}
          {describeError(toApiError(presets.error ?? encoders.error))}
        </p>
      )}
      <div className="row">
        <label>
          Preset{" "}
          <select value={preset} onChange={(e) => setPresetId(e.target.value)}>
            {(presets.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Encoder{" "}
          <select value={encoderId} onChange={(e) => setEncoderId(e.target.value)}>
            {(encoders.data?.encoders ?? []).map((e) => (
              <option key={e.id} value={e.id} disabled={!e.available}>
                {e.label}
                {e.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={blocked || Boolean(running) || start.busy}
          onClick={() => void start.run(encoderId)}
        >
          Render
        </button>
      </div>
      {vertical && (
        <div className="notice-box">
          <p>
            Vertical output uses the saved vertical variant on each cut. Review every cut, protected
            HUD regions and privacy blurs before exporting.
          </p>
          {layoutWarningsForProject.length > 0 && (
            <ul aria-label="Vertical export warnings">
              {layoutWarningsForProject.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          <label className="check">
            <input
              type="checkbox"
              checked={reviewLayout}
              onChange={(e) => setReviewed(e.target.checked ? reviewSignature : "")}
            />
            I reviewed the current vertical layout and any removed or obscured regions
          </label>
        </div>
      )}
      {encoder?.quality_note && <p className="muted">{encoder.quality_note}</p>}
      {encoders.data?.encoders
        .filter((e) => !e.available && e.kind === "hardware")
        .map((e) => (
          <p key={e.id} className="muted visually-subtle">
            {e.label}: {e.reason}
          </p>
        ))}
      {text.length > 0 && (
        <div className="notice-box" role="status">
          <p>
            This version cannot draw {text.join(" or ")} yet. Rendering without them is your
            explicit choice; the project keeps them.
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={omitText}
              onChange={(e) => setOmitText(e.target.checked)}
            />
            Render without {text.join(" and ")}
          </label>
        </div>
      )}
      {running && (
        <p role="status">
          Rendering{percent(running) !== null ? ` (${percent(running)}%)` : ""}… You can cancel it
          in Background jobs; nothing is kept from a cancelled render.
        </p>
      )}
      {start.error && <p role="alert">{describeError(start.error)}</p>}
      {renders.data && renders.data.length > 0 && (
        <ol className="renders" aria-label="Renders">
          {renders.data.map((record) => (
            <RenderRow
              key={record.id}
              record={record}
              busy={Boolean(running) || start.busy}
              onFallback={() => {
                setEncoderId("libx264");
                void start.run("libx264");
              }}
            />
          ))}
        </ol>
      )}
    </section>
  );
}
