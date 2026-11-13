// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import {
  type ApiError,
  type AssetDerivedMedia,
  describeError,
  getAsset,
  getDerived,
  type MediaAsset,
  prepareDerived,
  relinkAsset,
} from "./api";
import { isActive, percent, upsertJob, useJobs } from "./jobs";
import { badges } from "./LibraryView";
import { fetchWaveform, formatDuration, mediaUrl, thumbnailUrl, type Waveform } from "./media";
import { useAction, useQuery } from "./query";
import { routeHref } from "./route";

type Artifact = AssetDerivedMedia["artifacts"][number];
type Choice = "proxy" | "original";

const NEEDS_WORK = new Set(["not_generated", "missing", "stale"]);

const STATUS_TEXT: Record<string, string> = {
  ready: "Ready",
  stale: "Ready (an update is available)",
  missing: "File missing, will be rebuilt",
  failed: "Failed",
  not_generated: "Not prepared yet",
  not_needed: "Not needed: the original plays directly",
  not_applicable: "Not applicable: this clip has no audio",
};

const KIND_TEXT: Record<string, string> = {
  proxy: "Playback copy",
  filmstrip: "Thumbnails",
  waveform: "Waveform",
};

function playable(artifact: Artifact | undefined): boolean {
  return artifact?.status === "ready" || artifact?.status === "stale";
}

function WaveformView({ assetId, durationMs }: { assetId: string; durationMs: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [wave, setWave] = useState<Waveform | null | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    fetchWaveform(assetId)
      .then((w) => {
        if (!cancelled) setWave(w);
      })
      .catch(() => {
        if (!cancelled) setWave(null);
      });
    return () => {
      cancelled = true;
    };
  }, [assetId]);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext?.("2d");
    if (!element || !context || !wave) return;
    const { width, height } = element;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#6b8afd";
    const n = wave.peaks.length;
    for (let x = 0; x < width; x++) {
      const from = Math.floor((x / width) * n);
      const to = Math.max(from + 1, Math.floor(((x + 1) / width) * n));
      let peak = 0;
      for (let i = from; i < to && i < n; i++) peak = Math.max(peak, wave.peaks[i] ?? 0);
      const h = Math.max(1, (peak / 255) * height);
      context.fillRect(x, (height - h) / 2, 1, h);
    }
  }, [wave]);
  if (wave === null) return <p className="muted">The waveform could not be shown.</p>;
  return (
    <canvas
      ref={canvas}
      className="waveform"
      width={800}
      height={64}
      role="img"
      aria-label={`Audio waveform, ${formatDuration(durationMs)}`}
    />
  );
}

function Details({ asset }: { asset: MediaAsset }) {
  const video = asset.video;
  const audio = asset.audio?.[0];
  const rows: [string, string][] = [
    ["Duration", formatDuration(asset.duration_ms)],
    ["Container", asset.container ?? "—"],
  ];
  if (video) {
    rows.push(["Video", `${video.codec}, ${video.width}×${video.height}`]);
    rows.push(["Frame rate", `${(video.frame_rate.num / video.frame_rate.den).toFixed(2)} fps`]);
    if (video.color.hdr) rows.push(["Color", `HDR (${video.color.transfer ?? "flagged"})`]);
    if (video.rotation) rows.push(["Rotation", `${video.rotation}°`]);
  }
  rows.push(["Audio", audio ? `${audio.codec}, ${audio.channels} ch` : "None"]);
  if (asset.size_bytes) rows.push(["Size", `${(asset.size_bytes / 1048576).toFixed(1)} MB`]);
  rows.push([
    "Kept as",
    asset.import_mode === "managed" ? "Copy in the library" : "Reference to the original file",
  ]);
  return (
    <dl className="details">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** One asset: playback (proxy or original), derived-media status, details. */
export function AssetView({ id, at }: { id: string; at?: number }) {
  const asset = useQuery(`assets:${id}`, () => getAsset(id));
  const derived = useQuery(`derived:${id}`, () => getDerived(id));
  const { jobs, loaded: jobsLoaded } = useJobs();
  const job = jobs.find(
    (j) => j.kind === "proxy" && (j.params as { asset_id?: string } | undefined)?.asset_id === id,
  );
  const running = job !== undefined && isActive(job);
  const prepare = useAction(async (force: boolean) => {
    upsertJob(await prepareDerived(id, force ? { force: true } : {}));
  });
  const relink = useAction(async () => {
    const path = await open({
      directory: false,
      multiple: false,
      title: "Locate this clip or restore access",
    });
    if (typeof path === "string") upsertJob(await relinkAsset(id, path));
  });
  const [choice, setChoice] = useState<Choice | null>(null);
  const [playErrorFor, setPlayErrorFor] = useState<Choice | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const autoStarted = useRef(false);

  const artifacts = derived.data?.artifacts ?? [];
  const proxy = artifacts.find((a) => a.kind === "proxy");
  const filmstrip = artifacts.find((a) => a.kind === "filmstrip");
  const waveform = artifacts.find((a) => a.kind === "waveform");
  const decision = derived.data?.proxy_decision;
  const missing = Boolean(asset.data?.missing_at);
  const proxyOk = playable(proxy);
  const originalOk = !missing && decision !== undefined;
  const preferred: Choice | null = proxyOk ? "proxy" : originalOk ? "original" : null;
  const active = choice ?? preferred;
  const playError = active !== null && playErrorFor === active;

  // Prepare playback media automatically the first time it is needed.
  useEffect(() => {
    if (autoStarted.current || !derived.data || !jobsLoaded || running || missing) return;
    if (derived.data.artifacts.some((a) => NEEDS_WORK.has(a.status))) {
      autoStarted.current = true;
      void prepare.run(false);
    }
  }, [derived.data, jobsLoaded, running, missing, prepare]);

  if (asset.error) {
    return (
      <section className="view" aria-labelledby="asset-heading">
        <a href={routeHref({ view: "library" })}>← Library</a>
        <h1 id="asset-heading">Clip not available</h1>
        <p role="alert">{describeError(asset.error)}</p>
      </section>
    );
  }
  if (!asset.data) {
    return (
      <section className="view">
        <p role="status">Loading clip…</p>
      </section>
    );
  }
  const data = asset.data;
  const proxyError = proxy?.last_error as ApiError | undefined;

  return (
    <section className="view asset" aria-labelledby="asset-heading">
      <a href={routeHref({ view: "library" })}>← Library</a>
      <h1 id="asset-heading">{data.original_name}</h1>
      <p className="badges">
        {badges(data).map((tag) => (
          <span key={tag} className={tag === "Original missing" ? "badge warn" : "badge"}>
            {tag}
          </span>
        ))}
      </p>

      {missing && (
        <div className="notice-box warn" role="status">
          <strong>The original file is missing or offline.</strong> It may be on a disconnected
          drive or was moved. Nothing was deleted: the library keeps its details
          {proxyOk ? " and the playback copy still plays" : ""}. Reconnect the drive to play the
          original again.
        </div>
      )}
      {(missing || playError) && (
        <div className="row">
          <button type="button" disabled={relink.busy} onClick={() => void relink.run()}>
            Locate original or restore access…
          </button>
          {relink.error && <p role="alert">{describeError(relink.error)}</p>}
        </div>
      )}

      <div className="player">
        {active ? (
          <video
            key={active}
            ref={video}
            controls
            preload="metadata"
            src={mediaUrl(id, active)}
            aria-label={`${data.original_name}, ${active === "proxy" ? "playback copy" : "original file"}`}
            onError={() => setPlayErrorFor(active)}
            onLoadedMetadata={(e) => {
              // Opened from a search result: start at the matching moment.
              if (at !== undefined) e.currentTarget.currentTime = at / 1000;
            }}
          />
        ) : (
          <div className="player-empty" role="status">
            {running
              ? `Preparing a playback copy${job && percent(job) !== null ? ` (${percent(job)}%)` : ""}…`
              : derived.loading
                ? "Checking playback…"
                : "Nothing can be played yet."}
          </div>
        )}
        {playError && (
          <p role="alert">
            {active === "original"
              ? "This file cannot be played here. Use the playback copy instead."
              : "The playback copy could not be played."}
          </p>
        )}
        <fieldset className="choice" disabled={!proxyOk && !originalOk}>
          <legend>Play</legend>
          <label>
            <input
              type="radio"
              name="play-source"
              checked={active === "proxy"}
              disabled={!proxyOk}
              onChange={() => setChoice("proxy")}
            />{" "}
            Playback copy
          </label>
          <label>
            <input
              type="radio"
              name="play-source"
              checked={active === "original"}
              disabled={!originalOk}
              onChange={() => setChoice("original")}
            />{" "}
            Original file
          </label>
        </fieldset>
        {decision?.needed && !proxyOk && originalOk && (
          <p className="muted">
            The original may not play smoothly here (
            {decision.reasons.map((r) => r.detail).join(" ")})
          </p>
        )}
      </div>

      {waveform && playable(waveform) && (
        <WaveformView assetId={id} durationMs={data.duration_ms} />
      )}

      {filmstrip && playable(filmstrip) && filmstrip.filmstrip && (
        <ol className="filmstrip" aria-label="Thumbnails">
          {filmstrip.filmstrip.times_ms.map((t, i) => (
            <li key={t}>
              <button
                type="button"
                aria-label={`Jump to ${formatDuration(t)}`}
                onClick={() => {
                  if (video.current) video.current.currentTime = t / 1000;
                }}
              >
                <img src={thumbnailUrl(id, i + 1)} alt="" loading="lazy" />
              </button>
            </li>
          ))}
        </ol>
      )}

      <section aria-labelledby="derived-heading">
        <h2 id="derived-heading">Playback media</h2>
        {derived.error && <p role="alert">{describeError(derived.error)}</p>}
        <ul className="derived">
          {artifacts.map((artifact) => (
            <li key={artifact.kind}>
              <span>{KIND_TEXT[artifact.kind]}</span>
              <span className={`status status-${artifact.status}`}>
                {STATUS_TEXT[artifact.status] ?? artifact.status}
              </span>
            </li>
          ))}
        </ul>
        {proxy?.status === "failed" && proxyError && (
          <p role="alert">The playback copy could not be made: {describeError(proxyError)}</p>
        )}
        {running && <p role="status">{job.message ?? "Preparing playback media…"}</p>}
        {prepare.error && <p role="alert">{describeError(prepare.error)}</p>}
        <div className="row">
          <button
            type="button"
            disabled={running || prepare.busy || missing}
            onClick={() =>
              void prepare.run(artifacts.some((a) => a.status === "failed") ? false : true)
            }
          >
            {artifacts.some((a) => a.status === "failed") ? "Try again" : "Rebuild playback media"}
          </button>
        </div>
      </section>

      <section aria-labelledby="details-heading">
        <h2 id="details-heading">Details</h2>
        <Details asset={data} />
        <p className="muted">
          OpenWorld Moments only reads this file. It never changes, moves, or deletes your original.
        </p>
      </section>
    </section>
  );
}
