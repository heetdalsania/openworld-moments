// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { type ImportResult, type Job } from "./api";
import { jobLabel, watchJobs } from "./jobs";

/** The sentence a screen reader hears when background work ends, or null. */
export function announcement(job: Job): { text: string; urgent: boolean } | null {
  if (job.kind === "diagnostic") return null;
  const label = jobLabel(job);
  if (job.state === "ready") {
    const totals =
      job.kind === "import"
        ? (job.result as unknown as ImportResult | undefined)?.totals
        : undefined;
    if (totals) {
      const skipped = totals.skipped ? ` · ${totals.skipped} skipped` : "";
      const failed = totals.failed ? ` · ${totals.failed} failed` : "";
      return {
        text: `Import finished · ${totals.imported} added · ${totals.existing} already in library · ${totals.relinked} relinked${skipped}${failed}`,
        urgent: totals.failed > 0,
      };
    }
    return { text: `${label} finished.`, urgent: false };
  }
  if (job.state === "cancelled") return { text: `${label} cancelled.`, urgent: false };
  if (job.state === "failed")
    return {
      text: `${label} failed${job.error?.message ? `: ${job.error.message}` : "."}`,
      urgent: true,
    };
  return null;
}

/**
 * M31: one polite and one assertive live region for the whole app. Background jobs keep
 * running while the user is elsewhere, so their completion and failure are announced
 * wherever focus is. Only jobs seen running in this session are announced, so opening the
 * app does not read out old history.
 */
export function Announcer() {
  const [polite, setPolite] = useState("");
  const [urgent, setUrgent] = useState("");
  useEffect(() => {
    const seen = new Map<string, string>();
    return watchJobs((jobs) => {
      const politeLines: string[] = [];
      const urgentLines: string[] = [];
      for (const job of jobs) {
        const before = seen.get(job.id);
        seen.set(job.id, job.state);
        // First sight is only remembered: a running job is announced when it ends, and a
        // finished one is history.
        if (before === undefined || before === job.state || !unfinished(before)) continue;
        const message = announcement(job);
        if (message) (message.urgent ? urgentLines : politeLines).push(message.text);
      }
      if (politeLines.length || urgentLines.length) {
        setPolite(politeLines.join(" "));
        setUrgent(urgentLines.join(" "));
      }
    });
  }, []);
  return (
    <div className="job-notices">
      <div role="status" aria-live="polite" aria-atomic="true" data-testid="announce-polite">
        {polite && <p>{polite}</p>}
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true" data-testid="announce-urgent">
        {urgent && <p>{urgent}</p>}
      </div>
      {(polite || urgent) && (
        <button
          type="button"
          onClick={() => {
            setPolite("");
            setUrgent("");
          }}
        >
          Dismiss notification
        </button>
      )}
    </div>
  );
}

function unfinished(state: string): boolean {
  return state !== "ready" && state !== "failed" && state !== "cancelled";
}
