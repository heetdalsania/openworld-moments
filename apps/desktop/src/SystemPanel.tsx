// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId } from "react";
import { describeError, systemDoctor } from "./api";
import { architectureName, osName, platformInfo, supportName, supportNotes } from "./platform";
import { useQuery } from "./query";

const STATUS_WORD = { pass: "Passed", warn: "Warning", fail: "Failed" } as const;

/** The system check: storage, tools and local permissions. Shown in setup and Settings. */
export function SystemPanel({ heading = "System check" }: { heading?: string }) {
  const report = useQuery("system:doctor", systemDoctor);
  const platform = useQuery("system:platform", platformInfo);
  const id = useId();
  return (
    <section aria-labelledby={`${id}-heading`} className="panel runtime-check">
      <h2 id={`${id}-heading`}>{heading}</h2>
      <p>
        Media stays on this computer. Phone transfer and model downloads stay off until you allow
        them in Privacy choices.
      </p>
      {platform.data && (
        <div className="platform-summary">
          <p>
            {osName(platform.data)} · {architectureName(platform.data)} build · version{" "}
            {platform.data.host_version} · {supportName(platform.data)}
          </p>
          {supportNotes(platform.data).map((note) => (
            <p
              key={note}
              role={platform.data?.support.level === "unsupported" ? "alert" : undefined}
            >
              {note}
            </p>
          ))}
        </div>
      )}
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
          <ul className="checks">
            {report.data.checks.map((check) => (
              <li key={check.id} className={`check-${check.status}`}>
                <strong>
                  {STATUS_WORD[check.status]}: {check.id}
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
        </>
      )}
      <button type="button" disabled={report.loading} onClick={report.refetch}>
        Run system check again
      </button>
    </section>
  );
}
