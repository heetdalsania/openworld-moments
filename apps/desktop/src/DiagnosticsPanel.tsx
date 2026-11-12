// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { type DiagnosticsPreview, describeError, previewDiagnostics, saveDiagnostics } from "./api";
import { useAction } from "./query";

/**
 * M31 diagnostics export: preview first, then save. The report never contains footage,
 * file names, folder paths or tokens; failure messages are only added if the user opts
 * in, and are redacted too. Nothing is sent anywhere: the user decides who to share the
 * saved file with.
 */
export function DiagnosticsPanel({ workerReady }: { workerReady: boolean }) {
  const id = useId();
  const [includeMessages, setIncludeMessages] = useState(false);
  const [preview, setPreview] = useState<DiagnosticsPreview | null>(null);
  const [saved, setSaved] = useState<boolean | null>(null);
  const load = useAction(async () => {
    setSaved(null);
    setPreview(await previewDiagnostics(includeMessages));
  });
  const save = useAction(async () => {
    setSaved((await saveDiagnostics(includeMessages)).saved);
  });
  const error = load.error ?? save.error;
  return (
    <section className="panel diagnostics" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`}>Diagnostics for support</h2>
      <p>
        Save a report you can attach when asking for help. It lists app and tool versions, the
        system check, how many clips, sessions and projects you have, and recent error codes. It
        never contains footage, file names, folder paths or access tokens, and nothing is sent
        anywhere: you choose who to share the file with.
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={includeMessages}
          onChange={(e) => {
            setIncludeMessages(e.target.checked);
            setPreview(null);
            setSaved(null);
          }}
        />
        Include error messages (paths and file names are still removed)
      </label>
      <div className="row">
        <button type="button" disabled={!workerReady || load.busy} onClick={() => void load.run()}>
          {preview ? "Refresh preview" : "Preview report"}
        </button>
        <button
          type="button"
          disabled={!workerReady || !preview || save.busy}
          onClick={() => void save.run()}
        >
          Save report…
        </button>
      </div>
      {!workerReady && (
        <p role="status">The report is available once the media worker is running.</p>
      )}
      {load.busy && <p role="status">Preparing the report…</p>}
      {error && <p role="alert">{describeError(error)}</p>}
      {saved !== null && <p role="status">{saved ? "Report saved." : "Report not saved."}</p>}
      {preview && (
        <>
          <p className="muted">
            {preview.report.jobs.recent_failures.length === 1
              ? "1 recent failure"
              : `${preview.report.jobs.recent_failures.length} recent failures`}{" "}
            ·{" "}
            {preview.report.privacy.failure_messages === "omitted"
              ? "error messages left out"
              : "error messages included, redacted"}{" "}
            · saved as <code>{preview.filename}</code>
          </p>
          <pre
            className="diagnostics-preview"
            tabIndex={0}
            role="region"
            aria-label="Report preview"
          >
            {preview.content}
          </pre>
        </>
      )}
    </section>
  );
}
