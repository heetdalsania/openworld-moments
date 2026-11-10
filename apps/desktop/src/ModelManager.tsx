// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import {
  cancelJob,
  describeError,
  installModel,
  managedModels,
  pinModel,
  removeModel,
} from "./api";
import { isActive, upsertJob, useJobs } from "./jobs";
import { invalidate, useAction, useQuery } from "./query";

export function ModelManager() {
  const models = useQuery("models:managed", managedModels);
  const { jobs } = useJobs();
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const action = useAction(
    async (kind: "install" | "remove" | "pin" | "cancel", name: string, value?: string) => {
      if (kind === "install") upsertJob(await installModel(name));
      else if (kind === "cancel") {
        if (value) upsertJob(await cancelJob(value));
      } else if (kind === "pin" && value) await pinModel(name, value);
      else if (kind === "remove") {
        await removeModel(name);
        setConfirmRemove(null);
      }
      invalidate("models:", "transcript:models");
    },
  );
  const error = models.error ?? action.error;
  const downloading = jobs.some((job) => job.kind === "model_download" && isActive(job));
  return (
    <section aria-label="Optional models" className="panel model-manager">
      <h2>Optional speech models</h2>
      <p>
        Core editing works without these downloads. Models are pinned to the signed catalog bundled
        with this app. Installing uses your internet connection; audio and transcripts are never
        uploaded. Transcription also needs a local whisper.cpp engine; the Transcript panel reports
        engine availability.
      </p>
      {models.loading && <p role="status">Verifying catalog and installed checksums…</p>}
      {error && <p role="alert">{describeError(error)}</p>}
      {models.data?.models.length === 0 && <p>No optional models are listed in this catalog.</p>}
      {!models.error &&
        models.data?.models.map((model) => {
          const matching = jobs.filter(
            (job) =>
              job.kind === "model_download" &&
              (job.params as { name?: string } | undefined)?.name === model.name,
          );
          const latest = matching.find(isActive) ?? matching[0];
          const running = latest !== undefined && isActive(latest);
          const installed = model.active_sha256 === model.sha256;
          return (
            <article key={model.name} aria-label={`Model ${model.name}`}>
              <h3>
                {model.name} ·{" "}
                {installed ? "Verified installed" : "Not installed at catalog version"}
              </h3>
              <p>
                {Math.ceil(model.size_bytes / 1024 ** 2)} MiB · {model.license} · Needs up to{" "}
                {Math.ceil(model.disk_required_bytes / 1024 ** 2)} MiB additional space
              </p>
              <p>
                <a href={model.source_url} target="_blank" rel="noreferrer">
                  Model source and license
                </a>
              </p>
              <details>
                <summary>Version pin and checksum</summary>
                <p>Revision {model.revision}</p>
                <code>{model.sha256}</code>
              </details>
              {latest && (
                <p role="status">
                  {latest.state}: {latest.message ?? "Model installation"}
                  {latest.progress &&
                    ` (${Math.floor((100 * latest.progress.done) / latest.progress.total)}%)`}
                  {latest.error && ` — ${latest.error.message}`}
                </p>
              )}
              {!running && !installed && (
                <button
                  disabled={action.busy || models.loading || downloading}
                  onClick={() => void action.run("install", model.name)}
                >
                  {model.downloaded_bytes ? "Resume install" : "Install"} {model.name}
                </button>
              )}
              {running && (
                <button
                  disabled={action.busy}
                  onClick={() => void action.run("cancel", model.name, latest.id)}
                >
                  Cancel {model.name}
                </button>
              )}
              {model.versions.map((digest) => (
                <button
                  key={digest}
                  disabled={downloading || action.busy || model.active_sha256 === digest}
                  onClick={() => void action.run("pin", model.name, digest)}
                >
                  Use verified version {digest.slice(0, 12)}
                </button>
              ))}
              {(model.active_sha256 || model.versions.length > 0 || model.downloaded_bytes > 0) &&
                !running && (
                  <button
                    disabled={action.busy || downloading}
                    onClick={() => setConfirmRemove(model.name)}
                  >
                    Remove {model.name}…
                  </button>
                )}
              {confirmRemove === model.name && (
                <div>
                  <p>
                    Remove this model, its saved versions and unfinished download? Media and
                    transcripts stay in your library.
                  </p>
                  <button
                    disabled={action.busy}
                    onClick={() => void action.run("remove", model.name)}
                  >
                    Confirm remove {model.name}
                  </button>
                  <button onClick={() => setConfirmRemove(null)}>Keep model</button>
                </div>
              )}
            </article>
          );
        })}
      <button disabled={models.loading || action.busy} onClick={models.refetch}>
        Verify models again
      </button>
    </section>
  );
}
