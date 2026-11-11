// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId } from "react";
import {
  type ApiError,
  cancelJob,
  describeError,
  type ImportResult,
  type Job,
  retryJob,
} from "./api";
import { isActive, jobLabel, percent, reloadJobs, stateLabel, upsertJob, useJobs } from "./jobs";
import { useAction } from "./query";
import { navigate } from "./route";

function ImportSummary({ result }: { result: ImportResult }) {
  const { totals } = result;
  const failed = result.items.filter((i) => i.error);
  const parts = [
    [totals.imported, "imported"],
    [totals.existing, "already in the library"],
    [totals.relinked, "found again"],
    [totals.skipped, "skipped"],
    [totals.failed, "failed"],
  ] as const;
  const firstAsset = result.items.find((i) => i.asset_id)?.asset_id;
  return (
    <div className="import-summary">
      <p>
        {parts
          .filter(([n]) => n > 0)
          .map(([n, label]) => `${n} ${label}`)
          .join(" · ") || "No files found"}
      </p>
      {failed.length > 0 && (
        <ul aria-label="Files that were not imported">
          {failed.slice(0, 20).map((item, i) => (
            <li key={`${item.source}-${item.relative_path ?? i}`}>
              <span className="file">{item.relative_path ?? `Selection ${item.source + 1}`}</span>:{" "}
              {item.error ? describeError(item.error as ApiError) : "not imported"}
            </li>
          ))}
          {failed.length > 20 && <li>…and {failed.length - 20} more</li>}
        </ul>
      )}
      {firstAsset && (
        <button
          type="button"
          className="link"
          onClick={() => navigate({ view: "asset", id: firstAsset })}
        >
          Open the first imported clip
        </button>
      )}
    </div>
  );
}

function JobRow({ job }: { job: Job }) {
  const cancel = useAction(async () => upsertJob(await cancelJob(job.id)));
  const retry = useAction(async () => upsertJob(await retryJob(job.id)));
  const done = percent(job);
  const label = jobLabel(job);
  const error = job.error;
  const actionError = cancel.error ?? retry.error;
  return (
    <li className={`job job-${job.state}`} aria-label={`${label}: ${stateLabel(job)}`}>
      <div className="job-head">
        <strong>{label}</strong>
        <span className="job-state">{stateLabel(job)}</span>
      </div>
      {isActive(job) && (
        <progress
          max={100}
          value={done ?? undefined}
          aria-label={`${label} progress`}
          aria-valuetext={done === null ? "In progress" : `${done}%`}
        />
      )}
      {job.message && <p className="muted">{job.message}</p>}
      {job.state === "failed" && error && (
        <div className="job-error">
          <p role="alert">{describeError(error)}</p>
          {error.stderr_tail && (
            <details>
              <summary>Technical details</summary>
              <p className="muted">Code: {error.code}</p>
              <pre>{error.stderr_tail}</pre>
            </details>
          )}
        </div>
      )}
      {job.state === "cancelled" && (
        <p className="muted">
          {job.kind === "model_download"
            ? "Cancelled. The partial download is kept so you can resume it in Settings."
            : "Cancelled. Nothing partial was kept."}
        </p>
      )}
      {job.kind === "import" && job.result && (
        <ImportSummary result={job.result as unknown as ImportResult} />
      )}
      <div className="row">
        {isActive(job) && (
          <button type="button" disabled={cancel.busy} onClick={() => void cancel.run()}>
            Cancel {label.toLowerCase()}
          </button>
        )}
        {job.state === "failed" && error?.retryable && (
          <button type="button" disabled={retry.busy} onClick={() => void retry.run()}>
            Retry {label.toLowerCase()}
          </button>
        )}
      </div>
      {actionError && <p role="alert">{describeError(actionError)}</p>}
    </li>
  );
}

/** Background jobs: durable state from the worker, live via job events. */
export function JobCenter({ onClose }: { onClose: () => void }) {
  const { jobs, loaded, error } = useJobs();
  const headingId = useId();
  const visible = jobs.filter((j) => j.kind !== "diagnostic").slice(0, 50);
  return (
    <aside className="job-center" aria-labelledby={headingId}>
      <div className="job-center-head">
        <h2 id={headingId}>Background jobs</h2>
        <button type="button" onClick={onClose} aria-label="Close background jobs">
          Close
        </button>
      </div>
      {!loaded && <p role="status">Loading jobs…</p>}
      {error && (
        <div role="alert">
          <p>Jobs could not be loaded: {describeError(error)}</p>
          <button type="button" onClick={() => void reloadJobs()}>
            Try again
          </button>
        </div>
      )}
      {loaded && !error && visible.length === 0 && <p className="muted">No background jobs yet.</p>}
      <ul className="jobs">
        {visible.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </ul>
    </aside>
  );
}
