// SPDX-License-Identifier: AGPL-3.0-or-later
// Optional local transcription for a session (M18): privacy notice, engine and model
// status, transcribe / rebuild / delete, and timed lines that seek the session player.
import { useState } from "react";
import {
  deleteTranscript,
  describeError,
  getTranscript,
  type Job,
  speechModels,
  transcribeSession,
} from "./api";
import { isActive, upsertJob, useJobs } from "./jobs";
import { formatDuration } from "./media";
import { invalidate, useAction, useQuery } from "./query";

const LANGUAGES: [string, string][] = [
  ["auto", "Detect automatically"],
  ["en", "English"],
  ["es", "Spanish"],
  ["fr", "French"],
  ["de", "German"],
  ["pt", "Portuguese"],
  ["it", "Italian"],
  ["ja", "Japanese"],
];

const LOW_CONFIDENCE = 0.5;

function forSession(job: Job, sessionId: string): boolean {
  return (
    job.kind === "transcribe" &&
    (job.params as { session_id?: string } | undefined)?.session_id === sessionId
  );
}

function percent(job: Job): number | null {
  const p = job.progress;
  return p && p.total > 0 ? Math.round((p.done / p.total) * 100) : null;
}

export function TranscriptPanel({
  sessionId,
  onSeek,
}: {
  sessionId: string;
  onSeek: (virtualMs: number) => void;
}) {
  const status = useQuery("transcript:models", speechModels);
  const transcript = useQuery(`transcript:${sessionId}`, () => getTranscript(sessionId));
  const { jobs } = useJobs();
  const latest = jobs.find((j) => forSession(j, sessionId));
  const running = latest !== undefined && isActive(latest);
  const installed = status.data?.installed ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const model = chosen ?? installed[0]?.name ?? "";
  const [language, setLanguage] = useState("auto");
  const [confirming, setConfirming] = useState(false);
  const start = useAction(async (force: boolean) => {
    upsertJob(await transcribeSession(sessionId, { model, language, force }));
  });
  const remove = useAction(async () => {
    await deleteTranscript(sessionId);
    setConfirming(false);
    invalidate(`transcript:${sessionId}`);
  });
  const segments = transcript.data?.segments ?? [];
  const engine = status.data?.engine;
  const ready = engine?.available === true && installed.length > 0;
  const actionError = start.error ?? remove.error;

  return (
    <section aria-labelledby="transcript-heading" className="transcript">
      <h2 id="transcript-heading">Transcript</h2>
      <p className="muted" id="transcript-privacy">
        Optional. Speech is transcribed on this computer by whisper.cpp with a model you install
        explicitly in Settings; nothing is uploaded. Model downloads happen only when you choose
        Install. Transcripts can contain private conversations. They stay in your library, and you
        can delete them at any time without affecting your videos.
      </p>

      {status.error && (
        <p role="alert">Transcription status could not be loaded: {describeError(status.error)}</p>
      )}
      {engine && !engine.available && (
        <div className="notice-box" role="status">
          <p>{engine.reason}</p>
          <p className="muted">
            See “Local transcription” in the project guides for installing whisper.cpp.
          </p>
        </div>
      )}
      {engine?.available && installed.length === 0 && (
        <div className="notice-box" role="status">
          <p>No speech model is installed, so nothing can be transcribed yet.</p>
          <p className="muted">
            Download a whisper.cpp model yourself (for example base.en, about 148 MB, MIT license),
            then install it with <code>owm models install</code>. The app never downloads models on
            its own.
          </p>
        </div>
      )}

      {ready && (
        <div className="row" aria-describedby="transcript-privacy">
          <label>
            Model{" "}
            <select value={model} onChange={(e) => setChosen(e.target.value)} disabled={running}>
              {installed.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name} ({m.license})
                </option>
              ))}
            </select>
          </label>
          <label>
            Language{" "}
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={running}
            >
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={running || start.busy}
            onClick={() => void start.run(segments.length > 0)}
          >
            {segments.length > 0 ? "Rebuild transcript" : "Transcribe speech"}
          </button>
        </div>
      )}

      {running && latest && (
        <p role="status">
          Transcribing{percent(latest) !== null ? ` (${percent(latest)}%)` : ""}… You can cancel it
          in Background jobs; finished clips are kept.
        </p>
      )}
      {!running && latest?.state === "failed" && latest.error && (
        <p role="alert">{describeError(latest.error)}</p>
      )}
      {actionError && <p role="alert">{describeError(actionError)}</p>}

      {segments.length > 0 && (
        <>
          <div className="row">
            {confirming ? (
              <>
                <span>Delete the transcript text? Your video files are not affected.</span>
                <button type="button" disabled={remove.busy} onClick={() => void remove.run()}>
                  Delete transcript
                </button>
                <button type="button" onClick={() => setConfirming(false)}>
                  Keep it
                </button>
              </>
            ) : (
              <button type="button" disabled={running} onClick={() => setConfirming(true)}>
                Delete transcript…
              </button>
            )}
          </div>
          <ol className="transcript-lines" aria-label={`${segments.length} transcript lines`}>
            {segments.map((segment) => (
              <li key={segment.id}>
                <button
                  type="button"
                  className="link"
                  onClick={() => onSeek(segment.start_ms)}
                  aria-label={`Play from ${formatDuration(segment.start_ms)}`}
                >
                  {formatDuration(segment.start_ms)}
                </button>{" "}
                <span>{segment.text}</span>
                {segment.confidence < LOW_CONFIDENCE && (
                  <span className="badge warn">Low confidence</span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
      {transcript.data && segments.length === 0 && ready && !running && (
        <p className="muted">This session has no transcript yet.</p>
      )}
    </section>
  );
}
