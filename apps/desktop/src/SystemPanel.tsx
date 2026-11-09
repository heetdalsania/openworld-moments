// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { describeError, systemDoctor } from "./api";
import { useQuery } from "./query";

const ACK = "owm-system-check-0.1";
function acknowledged(): boolean {
  try {
    return localStorage.getItem(ACK) === "reviewed";
  } catch {
    return false;
  }
}

export function SystemPanel({ firstRun = false }: { firstRun?: boolean }) {
  const [dismissed, setDismissed] = useState(acknowledged);
  const report = useQuery(firstRun && dismissed ? null : "system:doctor", systemDoctor);
  if (firstRun && !dismissed && report.error)
    return (
      <aside aria-label="System check unavailable">
        <h2>System check unavailable</h2>
        <p>{describeError(report.error)}</p>
        <a href="#/settings">Review system checks in Settings</a>
      </aside>
    );
  if (firstRun && (dismissed || !report.data?.packaged)) return null;
  return (
    <section aria-label="System check" className="panel runtime-check">
      <h2>{firstRun ? "Welcome — check this computer" : "System check"}</h2>
      <p>
        Media stays on this computer. Phone transfer is off until you open it. Models download only
        after you choose Install.
      </p>
      {report.loading && <p role="status">Checking storage, tools and local permissions…</p>}
      {report.error && <p role="alert">{describeError(report.error)}</p>}
      {report.data && (
        <>
          <p>
            {report.data.platform} / {report.data.architecture} ·{" "}
            {report.data.packaged ? "Packaged runtime" : "Development runtime"} ·{" "}
            {Math.floor(report.data.free_bytes / 1024 ** 2)} MiB free
          </p>
          <p role="status">
            {report.data.ready ? "Core checks passed" : "Repair the failed checks before importing"}
          </p>
          <ul>
            {report.data.checks.map((check) => (
              <li key={check.id}>
                <strong>
                  {check.status.toUpperCase()}: {check.id}
                </strong>{" "}
                — {check.message}
              </li>
            ))}
          </ul>
          <details>
            <summary>Runtime versions and licenses</summary>
            <p>WebView (managed by your operating system): {navigator.userAgent}</p>
            <ul>
              {report.data.tools.map((tool) => (
                <li key={tool.name}>
                  {tool.name} {tool.version} — {tool.origin}, {tool.license}
                  {tool.sha256 && <code> SHA-256 {tool.sha256}</code>}
                </li>
              ))}
            </ul>
          </details>
          {firstRun && (
            <button
              disabled={!report.data.ready || report.loading || report.error !== undefined}
              onClick={() => {
                try {
                  localStorage.setItem(ACK, "reviewed");
                } catch {
                  /* in-memory acknowledgement still works */
                }
                setDismissed(true);
              }}
            >
              Continue
            </button>
          )}
        </>
      )}
      <button disabled={report.loading} onClick={report.refetch}>
        Run system check again
      </button>
    </section>
  );
}
