// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { load } from "@openworld-moments/contracts";
import {
  describeError,
  exportCropSample,
  exportProfilePatch,
  getCalibration,
  getDerived,
  importProfilePatch,
  listAssets,
  listProfiles,
  prepareDerived,
  previewCalibration,
  resetCalibration,
  saveCalibration,
  toApiError,
  type CalibrationState,
  type MediaAsset,
} from "./api";
import {
  preprocess,
  regionDiff,
  validROI,
  type Preprocess,
  type Regions,
  type ROI,
} from "./calibration";
import { mediaUrl } from "./media";
import { setQueryData, useQuery } from "./query";
import { RoiCanvas } from "./RoiCanvas";

export function CalibrationView() {
  const profiles = useQuery("profiles", listProfiles);
  const [id, setId] = useState("");
  return (
    <section className="view calibration" aria-labelledby="calibration-heading">
      <h1 id="calibration-heading">Profile calibration</h1>
      <p>
        Choose an installed profile and a frame from your library. Adjust regions for your HUD
        layout, then save local overrides.
      </p>
      {profiles.loading && <p role="status">Loading profiles…</p>}
      {profiles.error && (
        <p role="alert">
          {describeError(profiles.error)} <button onClick={profiles.refetch}>Try again</button>
        </p>
      )}
      {profiles.data?.length === 0 && <p>No profiles are installed.</p>}
      <label>
        Installed profile{" "}
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">Choose profile</option>
          {profiles.data?.map((p) => (
            <option value={p.id} key={p.id}>
              {p.display_name} · {p.profile_version}
            </option>
          ))}
        </select>
      </label>
      {id && <LoadEditor key={id} id={id} />}
    </section>
  );
}
function LoadEditor({ id }: { id: string }) {
  const query = useQuery(`calibration:${id}`, () => getCalibration(id));
  const [revision, setRevision] = useState(0);
  const [reloadError, setReloadError] = useState("");
  async function reload() {
    try {
      const fresh = await getCalibration(id);
      setQueryData(`calibration:${id}`, fresh);
      setRevision((r) => r + 1);
      setReloadError("");
    } catch (e) {
      setReloadError(describeError(toApiError(e)));
    }
  }
  if (query.error)
    return (
      <p role="alert">
        {describeError(query.error)} <button onClick={query.refetch}>Try again</button>
      </p>
    );
  if (!query.data) return <p role="status">Loading profile regions…</p>;
  return (
    <>
      <button onClick={() => void reload()}>Reload installed profile and saved overrides</button>
      {reloadError && <p role="alert">{reloadError}</p>}
      <Editor key={`${query.data.base_key}:${revision}`} initial={query.data} />
    </>
  );
}

function Editor({ initial }: { initial: CalibrationState }) {
  const [saved, setSaved] = useState(initial);
  const [regions, setRegions] = useState(initial.effective.regions as Regions);
  const [selected, setSelected] = useState(Object.keys(regions)[0] ?? "");
  const [name, setName] = useState("");
  const [compare, setCompare] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Preprocess>("color");
  const [threshold, setThreshold] = useState(200);
  const [frame, setFrame] = useState<{
    image: string;
    canvas: HTMLCanvasElement;
    width: number;
    height: number;
    time: number;
  } | null>(null);
  const crop = useRef<HTMLCanvasElement>(null);
  const [brightness, setBrightness] = useState<number | null>(null);
  const base = saved.base.regions as Regions;
  const diff = regionDiff(base, regions);
  const dirty = JSON.stringify(regions) !== JSON.stringify(saved.effective.regions);
  const valid = Object.values(regions).every(validROI);
  const r = regions[selected];
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(describeError(toApiError(e)));
    } finally {
      setBusy(false);
    }
  }
  function accept(state: CalibrationState) {
    setQueryData(`calibration:${state.base.id}`, state);
    setSaved(state);
    setRegions(state.effective.regions as Regions);
    setSelected(Object.keys(state.effective.regions)[0] ?? "");
  }
  useEffect(() => {
    const out = crop.current;
    if (!frame || !r || !validROI(r) || !out) {
      setBrightness(null);
      return;
    }
    const [x, y, w, h] = r;
    out.width = Math.max(1, Math.round(w * frame.canvas.width));
    out.height = Math.max(1, Math.round(h * frame.canvas.height));
    const ctx = out.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(
      frame.canvas,
      x * frame.canvas.width,
      y * frame.canvas.height,
      w * frame.canvas.width,
      h * frame.canvas.height,
      0,
      0,
      out.width,
      out.height,
    );
    const img = ctx.getImageData(0, 0, out.width, out.height);
    const gray = new Uint8ClampedArray(img.data);
    preprocess(gray, "gray", threshold);
    let sum = 0;
    for (let i = 0; i < gray.length; i += 4) sum += gray[i] ?? 0;
    setBrightness(sum / (gray.length / 4));
    preprocess(img.data, mode, threshold);
    ctx.putImageData(img, 0, 0);
  }, [frame, r, mode, threshold]);
  return (
    <>
      <p className="muted">
        Base {saved.base.profile_version} · {saved.base.game_family} ·{" "}
        {saved.base.frame.aspect_ratios.join(", ")} · minimum {saved.base.frame.min_width} ×{" "}
        {saved.base.frame.min_height} · locales{" "}
        {Object.keys(saved.base.locales ?? {}).join(", ") || "none"} · {saved.base.license}
      </p>
      {saved.base_changed && (
        <p className="banner warn">
          The installed profile changed since this patch was created. Overrides are retained;
          compare them with the new defaults before saving.
        </p>
      )}
      {saved.conflict && <p role="alert">{saved.conflict} Reset or import a compatible patch.</p>}
      <FrameSelector onFrame={setFrame} disabled={busy} />
      <div className="calibration-grid">
        <section aria-label="Frame and regions">
          <div className="row">
            <label>
              New region name{" "}
              <input
                value={name}
                maxLength={64}
                placeholder="subtitle"
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !/^[a-z0-9]+(?:[-_][a-z0-9]+)*$/.test(name) || name in regions}
              onClick={() => {
                setRegions({ ...regions, [name]: [0.25, 0.25, 0.5, 0.5] });
                setSelected(name);
                setName("");
              }}
            >
              Add region
            </button>
          </div>
          <label>
            <input
              type="checkbox"
              checked={compare}
              onChange={(e) => setCompare(e.target.checked)}
            />{" "}
            Compare base outlines (dashed)
          </label>
          {frame ? (
            <RoiCanvas
              image={frame.image}
              width={frame.width}
              height={frame.height}
              regions={regions}
              base={base}
              selected={selected}
              name={name}
              compare={compare}
              onSelect={setSelected}
              onChange={setRegions}
            />
          ) : (
            <p className="empty">
              Capture a representative frame to draw regions. Numeric controls work without a frame.
            </p>
          )}
          <p className="muted">
            {frame
              ? `Captured at ${(frame.time / 1000).toFixed(3)} s. Coordinates use the upright ${frame.width} × ${frame.height} picture; preview uses the SDR playback copy.`
              : "Coordinates: x, y, width, height, normalized from 0 to 1."}
          </p>
        </section>
        <section className="panel" aria-label="Region settings">
          <h2>Regions</h2>
          <label>
            Selected region{" "}
            <select value={selected} onChange={(e) => setSelected(e.target.value)}>
              <option value="">Choose region</option>
              {Object.keys(regions).map((key) => (
                <option key={key}>{key}</option>
              ))}
            </select>
          </label>
          {r && (
            <>
              <fieldset>
                <legend>Normalized bounds</legend>
                {["X", "Y", "Width", "Height"].map((label, i) => (
                  <label key={label}>
                    {label}
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.0001"
                      value={Number.isFinite(r[i]) ? r[i] : ""}
                      onChange={(e) => {
                        const next = [...r] as ROI;
                        next[i] = e.target.value === "" ? NaN : Number(e.target.value);
                        setRegions({ ...regions, [selected]: next });
                      }}
                    />
                  </label>
                ))}
              </fieldset>
              {!validROI(r) && (
                <p role="alert">
                  Bounds must be finite, positive in size, and fit entirely inside the picture.
                </p>
              )}
              {selected in base ? (
                <button onClick={() => setRegions({ ...regions, [selected]: base[selected] ?? r })}>
                  Reset selected to base
                </button>
              ) : (
                <button
                  onClick={() => {
                    setRegions(
                      Object.fromEntries(
                        Object.entries(regions).filter(([key]) => key !== selected),
                      ),
                    );
                    setSelected(Object.keys(base)[0] ?? "");
                  }}
                >
                  Remove custom region
                </button>
              )}
              <h3>Crop preview</h3>
              <label>
                Preprocessing{" "}
                <select value={mode} onChange={(e) => setMode(e.target.value as Preprocess)}>
                  <option value="color">Color</option>
                  <option value="gray">Grayscale</option>
                  <option value="threshold">Threshold</option>
                </select>
              </label>
              {mode === "threshold" && (
                <label>
                  Threshold{" "}
                  <input
                    type="number"
                    min={0}
                    max={255}
                    value={threshold}
                    onChange={(e) =>
                      setThreshold(Math.max(0, Math.min(255, Number(e.target.value))))
                    }
                  />
                </label>
              )}
              <canvas
                ref={crop}
                className="crop-preview"
                aria-label="Preprocessed region crop"
                hidden={!frame || !validROI(r)}
              />
              {frame &&
                brightness !== null &&
                saved.base.detectors.some(
                  (d) => d.id === "synthetic-bright-region" && d.enabled,
                ) && (
                  <p>
                    Single-frame synthetic signal:{" "}
                    {brightness >= 200 ? "bright" : "below threshold"} (mean grayscale{" "}
                    {brightness.toFixed(1)} / 255). Temporal confirmation is not tested here; this
                    is not a gameplay event.
                  </p>
                )}
              <button
                disabled={!frame || !valid || busy}
                onClick={() =>
                  void action(async () => {
                    if (!frame) return;
                    const sample = document.createElement("canvas");
                    sample.width = 64;
                    sample.height = 36;
                    const context = sample.getContext("2d");
                    if (!context) throw new Error("Cannot read a sample.");
                    context.drawImage(frame.canvas, 0, 0, 64, 36);
                    const data = context.getImageData(0, 0, 64, 36).data;
                    preprocess(data, "gray", 200);
                    const gray = Array.from({ length: 2304 }, (_, i) => data[i * 4] ?? 0);
                    const result = await previewCalibration(
                      saved.base.id,
                      saved.base_key,
                      regions,
                      gray,
                      frame.time,
                    );
                    setMessage(
                      result.available
                        ? `${result.detector_id} ${result.detector_version}: ${(result.detections ?? []).length} detections from one sample; requires ${result.confirmation_frames} confirmation frames. Preview only, no events saved.`
                        : (result.message ?? "No detector preview available."),
                    );
                  })
                }
              >
                Preview built-in detector
              </button>
              <button
                disabled={!frame || !validROI(r) || busy}
                onClick={() =>
                  void action(async () => {
                    const output = crop.current;
                    if (!output) throw new Error("No crop available.");
                    const blob = await new Promise<Blob | null>((resolve) =>
                      output.toBlob(resolve, "image/png"),
                    );
                    if (!blob) throw new Error("Cannot encode this crop.");
                    const ok = await exportCropSample(
                      Array.from(new Uint8Array(await blob.arrayBuffer())),
                    );
                    setMessage(
                      ok
                        ? "Crop sample exported separately. It contains image content."
                        : "Crop export cancelled.",
                    );
                  })
                }
              >
                Export crop sample…
              </button>
            </>
          )}
        </section>
      </div>
      <section aria-label="Changes from base">
        <h2>Changes from base</h2>
        {Object.keys(diff).length ? (
          <ul>
            {Object.entries(diff).map(([key, value]) => (
              <li key={key}>
                <strong>{key}</strong>: {base[key] ? JSON.stringify(base[key]) : "new region"} →{" "}
                {JSON.stringify(value)}
              </li>
            ))}
          </ul>
        ) : (
          <p>Exactly the base region values.</p>
        )}
      </section>
      <div className="row">
        <button
          className="primary"
          disabled={busy || !valid || Boolean(saved.conflict)}
          onClick={() =>
            void action(async () => {
              accept(await saveCalibration(saved.base.id, saved.base_key, regions));
              setMessage("Local overrides saved. Installed profile unchanged.");
            })
          }
        >
          Save local overrides
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void action(async () => {
              accept(await resetCalibration(saved.base.id));
              setMessage("Reset to the current base profile.");
            })
          }
        >
          Reset all to base
        </button>
        <button
          disabled={busy || dirty || !saved.patch || Boolean(saved.conflict)}
          onClick={() =>
            void action(async () =>
              setMessage(
                (await exportProfilePatch(saved.base.id))
                  ? "Profile patch exported. No frames or footage included."
                  : "Patch export cancelled.",
              ),
            )
          }
        >
          Export saved patch…
        </button>
        <label className="button">
          Import patch…
          <input
            aria-label="Import profile patch"
            type="file"
            accept=".json,application/json"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file)
                void action(async () => {
                  if (file.size > 65536) throw new Error("Patch exceeds 64 KiB.");
                  const patch = load("profile-patch", JSON.parse(await file.text()));
                  accept(await importProfilePatch(saved.base.id, patch));
                  setMessage("Profile patch imported and saved locally.");
                });
            }}
          />
        </label>
      </div>
      <p role="status">
        {busy
          ? "Working…"
          : message ||
            (dirty
              ? "Unsaved region changes. Save before exporting a patch."
              : "Local overrides are separate from installed profiles.")}
      </p>
      {error && <p role="alert">{error}</p>}
      <p className="muted">
        Patch exports contain coordinates, profile identity, compatibility and tool provenance only.
        Crop samples contain image content and are exported only by their separate button. No model
        is downloaded.
      </p>
    </>
  );
}

function FrameSelector({
  onFrame,
  disabled,
}: {
  onFrame: (
    frame: {
      image: string;
      canvas: HTMLCanvasElement;
      width: number;
      height: number;
      time: number;
    } | null,
  ) => void;
  disabled: boolean;
}) {
  const assets = useQuery("calibration-assets", () => listAssets());
  const [more, setMore] = useState<MediaAsset[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [asset, setAsset] = useState<MediaAsset | null>(null);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [preparing, setPreparing] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const derived = useQuery(asset ? `asset:${asset.id}:derived` : null, () =>
    getDerived(asset?.id ?? ""),
  );
  const proxy = derived.data?.artifacts.find((a) => a.kind === "proxy" && a.status === "ready");
  const available = [...(assets.data ?? []), ...more];
  const [time, setTime] = useState(0);
  function capture() {
    try {
      const v = video.current;
      const metadata = asset?.video;
      if (!v || !metadata) throw new Error("No frame available.");
      v.pause();
      const canvas = document.createElement("canvas");
      canvas.width = v.videoWidth;
      canvas.height = v.videoHeight;
      if (canvas.width < 1 || canvas.height < 1 || canvas.width * canvas.height > 1920 * 1920)
        throw new Error("Playback frame is unavailable or too large.");
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Frame capture is unavailable.");
      context.drawImage(v, 0, 0);
      const rotated = asset?.video?.rotation === 90 || asset?.video?.rotation === 270;
      const width = rotated ? metadata.height : metadata.width;
      const height = rotated ? metadata.width : metadata.height;
      onFrame({
        canvas,
        image: canvas.toDataURL("image/png"),
        width,
        height,
        time: Math.round(v.currentTime * 1000),
      });
      setStatus("Frame captured. Seek and capture again to replace it.");
      setError("");
    } catch {
      setError("This frame could not be read. Prepare the playback copy and try again.");
    }
  }
  return (
    <section className="panel" aria-label="Representative frame">
      <h2>Representative frame</h2>
      {assets.loading && <p role="status">Loading imported clips…</p>}
      {assets.error && (
        <p role="alert">
          {describeError(assets.error)} <button onClick={assets.refetch}>Try again</button>
        </p>
      )}
      {assets.data?.length === 0 && <p>Your library is empty. Import a clip first.</p>}
      <label>
        Imported clip{" "}
        <select
          disabled={disabled}
          value={asset?.id ?? ""}
          onChange={(e) => {
            if (e.target.value === asset?.id) return;
            setAsset(available.find((a) => a.id === e.target.value) ?? null);
            setReady(false);
            setTime(0);
            setStatus("");
            setError("");
            onFrame(null);
          }}
        >
          <option value="">Choose clip</option>
          {available
            .filter((a) => a.video)
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.original_name}
              </option>
            ))}
        </select>
      </label>
      {hasMore && (assets.data?.length ?? 0) >= 60 && (
        <button
          onClick={() =>
            void listAssets(available.at(-1)?.id)
              .then((rows) => {
                setMore([...more, ...rows]);
                setHasMore(rows.length === 60);
              })
              .catch((e) => setError(describeError(toApiError(e))))
          }
        >
          More clips
        </button>
      )}
      {asset && (
        <>
          {derived.loading && <p role="status">Checking playback copy…</p>}
          {derived.error && (
            <p role="alert">
              {describeError(derived.error)} <button onClick={derived.refetch}>Check again</button>
            </p>
          )}
          {!proxy ? (
            <>
              <p>Prepare an upright SDR playback copy before capturing a frame.</p>
              <button
                disabled={disabled || preparing}
                onClick={() => {
                  setPreparing(true);
                  void prepareDerived(asset.id, { proxy_policy: "always" })
                    .then(() =>
                      setStatus(
                        "Preparation queued. Its progress and Cancel control are in Background jobs. Check again when finished.",
                      ),
                    )
                    .catch((e) => setError(describeError(toApiError(e))))
                    .finally(() => setPreparing(false));
                }}
              >
                Prepare playback copy
              </button>
              <button onClick={derived.refetch}>Check again</button>
            </>
          ) : (
            <>
              <video
                key={asset.id}
                ref={video}
                crossOrigin="anonymous"
                src={mediaUrl(asset.id, "proxy")}
                controls
                preload="auto"
                className="calibration-video"
                onLoadedData={() => setReady(true)}
                onCanPlay={() => setReady(true)}
                onSeeking={() => setReady(false)}
                onSeeked={() => setReady(true)}
                onTimeUpdate={() => setTime(Math.round((video.current?.currentTime ?? 0) * 1000))}
                onError={() => {
                  setReady(false);
                  setError("Playback copy could not be decoded. Rebuild it from the clip page.");
                }}
              />
              <label>
                Frame time (ms){" "}
                <input
                  type="number"
                  min={0}
                  max={Math.max(0, asset.duration_ms - 1)}
                  value={time}
                  onChange={(e) => {
                    const value = Math.max(
                      0,
                      Math.min(asset.duration_ms - 1, Number(e.target.value)),
                    );
                    setTime(value);
                    if (video.current) {
                      video.current.pause();
                      video.current.currentTime = value / 1000;
                    }
                  }}
                />
              </label>
              <button disabled={disabled || !ready} onClick={capture}>
                Capture this frame
              </button>
              <button
                onClick={() => {
                  onFrame(null);
                  setStatus("Frame selection cleared.");
                }}
              >
                Clear captured frame
              </button>
            </>
          )}
        </>
      )}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
