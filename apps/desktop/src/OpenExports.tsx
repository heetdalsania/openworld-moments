// SPDX-License-Identifier: AGPL-3.0-or-later
// Open formats (M27): save the saved project as documented files for other tools.
// The host writes the file through a native save dialog; absolute file locations are
// included only when the user ticks the box, and only for formats that reference media.
import { useState } from "react";
import { describeError, type ExportFormat, type ExportWarning, saveProjectExport } from "./api";
import { useAction } from "./query";

export const EXPORT_FORMATS: { id: ExportFormat; label: string; paths: boolean; note: string }[] = [
  {
    id: "project",
    label: "OpenWorld Moments project (JSON)",
    paths: true,
    note: "Everything in the project, versioned and readable by this app and other tools.",
  },
  {
    id: "events",
    label: "Session events (JSONL)",
    paths: false,
    note: "One event per line with evidence, provenance, your review and project times.",
  },
  { id: "srt", label: "Captions (SRT)", paths: false, note: "Caption text and timing." },
  { id: "vtt", label: "Captions (WebVTT)", paths: false, note: "Caption text and timing." },
  {
    id: "csv",
    label: "Markers (CSV)",
    paths: false,
    note: "Cuts, events, captions, overlays and audio ranges as rows for spreadsheets.",
  },
  {
    id: "otio",
    label: "OpenTimelineIO timeline",
    paths: true,
    note: "Cuts and markers for editors that read OpenTimelineIO.",
  },
  {
    id: "fcpxml",
    label: "FCPXML (experimental)",
    paths: true,
    note: "Experimental: cuts and markers for Final Cut Pro; timing may need checking.",
  },
];

export function OpenExports({
  projectId,
  flush,
  workerReady,
}: {
  projectId: string;
  flush: () => Promise<unknown>;
  workerReady: boolean;
}) {
  const [format, setFormat] = useState<ExportFormat>("project");
  const [includePaths, setIncludePaths] = useState(false);
  const [outcome, setOutcome] = useState<{ saved: boolean; warnings: ExportWarning[] } | null>(
    null,
  );
  const chosen = EXPORT_FORMATS.find((f) => f.id === format) ?? EXPORT_FORMATS[0];
  const save = useAction(async () => {
    setOutcome(null);
    // Export exactly what is saved: write pending edits first.
    await flush();
    setOutcome(await saveProjectExport(projectId, format, Boolean(chosen?.paths && includePaths)));
  });
  return (
    <section className="open-exports" aria-labelledby="open-exports-heading">
      <h3 id="open-exports-heading">Open formats</h3>
      <p className="muted">
        Save the last saved revision for other tools. Files never include where your clips are
        stored unless you choose to.
      </p>
      <div className="row">
        <label>
          Format{" "}
          <select
            value={format}
            onChange={(e) => {
              setFormat(e.target.value as ExportFormat);
              setOutcome(null);
            }}
          >
            {EXPORT_FORMATS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={!workerReady || save.busy} onClick={() => void save.run()}>
          Save export…
        </button>
      </div>
      <p className="muted">{chosen?.note}</p>
      {chosen?.paths && (
        <label className="check">
          <input
            type="checkbox"
            checked={includePaths}
            onChange={(e) => setIncludePaths(e.target.checked)}
          />
          Include file locations (full paths on this computer)
        </label>
      )}
      {outcome && (
        <div role="status">
          <p>{outcome.saved ? "Export saved." : "Export not saved."}</p>
          {outcome.saved && outcome.warnings.length > 0 && (
            <>
              <p>This format cannot represent everything in the project:</p>
              <ul aria-label="Export warnings">
                {outcome.warnings.map((w) => (
                  <li key={w.code}>
                    {w.detail}
                    {w.count && w.count > 1 ? ` (${w.count})` : ""}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {save.error && <p role="alert">{describeError(save.error)}</p>}
    </section>
  );
}
