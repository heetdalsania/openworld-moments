// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import type { Segment } from "@openworld-moments/contracts";
import {
  describeError,
  eventReview,
  getSession,
  prepareDerived,
  projectSelection,
  toApiError,
} from "./api";
import { thumbnailUrl } from "./media";
import { formatClock } from "./SessionView";
import { SessionPlayer, type PlayerState } from "./player";
import { loadProjectMedia, type ProjectMedia } from "./projectMedia";
import { newSegmentId, projectMarkers, projectTimeline } from "./projectTimeline";
import { openWorkspace, type ProjectWorkspace } from "./projectWorkspace";
import { useQuery } from "./query";
import { frameMs, nearestBoundary, toSource } from "./timeline";
import { SegmentWave } from "./TimelineWave";
import { CaptionPanel, CaptionPreview } from "./CaptionPanel";
import { AudioPanel } from "./AudioPanel";
import { ExportPanel } from "./ExportPanel";
import { LayoutPanel } from "./LayoutPanel";
import { PrivacyPanel } from "./PrivacyPanel";
import { VerticalPreview } from "./VerticalPreview";
import { audioAt, EditorAudio } from "./editorAudio";
import type { EditorCommand } from "./editor";

const initialPlayer: PlayerState = {
  virtualMs: 0,
  playing: false,
  segmentIndex: 0,
  activeElement: 0,
};

function CutInspector({
  cut,
  index,
  count,
  sourceDuration,
  onTrim,
  onMove,
  onRemove,
  onSplit,
  playhead,
}: {
  cut: Segment;
  index: number;
  count: number;
  sourceDuration: number;
  playhead: number;
  onTrim: (from: number, to: number) => void;
  onMove: (by: -1 | 1) => void;
  onRemove: () => void;
  onSplit: (offset: number) => void;
}) {
  const signature = JSON.stringify([cut.id, cut.source_in_ms, cut.source_out_ms]);
  const initialTrim = { signature, from: String(cut.source_in_ms), to: String(cut.source_out_ms) };
  const [trim, setTrim] = useState(initialTrim);
  // Only actual range changes reset fields; metadata/audio commands clone unchanged cuts.
  if (trim.signature !== signature) setTrim(initialTrim);
  const { from, to } = trim;
  const setFrom = (value: string) => setTrim({ ...trim, from: value });
  const setTo = (value: string) => setTrim({ ...trim, to: value });
  const [offset, setOffset] = useState(
    String(Math.max(1, Math.round((cut.source_out_ms - cut.source_in_ms) / 2))),
  );
  const commit = () => onTrim(Number(from), Number(to));
  const handleKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key))
      commit();
  };
  const cancelDrag = () => {
    setTrim(initialTrim);
  };
  return (
    <aside className="cut-inspector panel" aria-labelledby="cut-heading">
      <p className="eyebrow">
        SELECTED CUT {index + 1} / {count}
      </p>
      <h2 id="cut-heading">Shape this moment</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          commit();
        }}
      >
        <label>
          In handle
          <input
            type="range"
            aria-label="In trim handle"
            min={0}
            max={Math.max(0, Number(to) - 1)}
            step={1}
            value={Number(from)}
            onChange={(e) => setFrom(e.target.value)}
            onPointerUp={commit}
            onPointerCancel={cancelDrag}
            onKeyUp={handleKey}
          />
        </label>
        <label>
          Out handle
          <input
            type="range"
            aria-label="Out trim handle"
            min={Number(from) + 1}
            max={sourceDuration}
            step={1}
            value={Number(to)}
            onChange={(e) => setTo(e.target.value)}
            onPointerUp={commit}
            onPointerCancel={cancelDrag}
            onKeyUp={handleKey}
          />
        </label>
        <div className="trim-numbers">
          <label>
            Source in (ms)
            <input
              type="number"
              required
              min={0}
              max={sourceDuration - 1}
              step={1}
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label>
            Source out (ms)
            <input
              type="number"
              required
              min={1}
              max={sourceDuration}
              step={1}
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
        </div>
        <button className="primary" type="submit">
          Apply trim
        </button>
        <button type="button" onClick={cancelDrag}>
          Reset trim fields
        </button>
      </form>
      <p className="muted">
        Source range is end-exclusive. Drag a handle, use its arrow keys, or enter exact
        milliseconds.
      </p>
      <div className="row">
        <button disabled={index === 0} onClick={() => onMove(-1)}>
          Move earlier
        </button>
        <button disabled={index === count - 1} onClick={() => onMove(1)}>
          Move later
        </button>
      </div>
      <button className="danger" onClick={onRemove}>
        Remove selected cut
      </button>
      <form
        className="split-form"
        onSubmit={(e) => {
          e.preventDefault();
          onSplit(Number(offset));
        }}
      >
        <label>
          Split offset in cut (ms)
          <input
            type="number"
            min={1}
            max={cut.source_out_ms - cut.source_in_ms - 1}
            required
            step={1}
            value={offset}
            onChange={(e) => setOffset(e.target.value)}
          />
        </label>
        <button disabled={cut.source_out_ms - cut.source_in_ms < 2}>Split at offset</button>
      </form>
      <button
        disabled={
          playhead <= cut.timeline_start_ms ||
          playhead >= cut.timeline_start_ms + cut.source_out_ms - cut.source_in_ms
        }
        onClick={() => onSplit(playhead - cut.timeline_start_ms)}
      >
        Split at playhead
      </button>
    </aside>
  );
}

export function EditorView({ id, workerReady }: { id: string; workerReady: boolean }) {
  const [workspace, setWorkspace] = useState<ProjectWorkspace>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    openWorkspace(id).then(
      (w) => {
        if (!cancelled) {
          setWorkspace(w);
          setError(undefined);
        }
      },
      (e) => {
        if (!cancelled) setError(describeError(toApiError(e)));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [id, attempt]);
  if (!workspace)
    return (
      <section className="view">
        <a href="#/projects">← Projects</a>
        {error ? (
          <div role="alert">
            <p>{error}</p>
            <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
          </div>
        ) : (
          <p role="status">Opening editor…</p>
        )}
      </section>
    );
  return <LoadedEditor workspace={workspace} workerReady={workerReady} />;
}

function LoadedEditor({
  workspace,
  workerReady,
}: {
  workspace: ProjectWorkspace;
  workerReady: boolean;
}) {
  useSyncExternalStore(workspace.subscribe, workspace.snapshot);
  const document = workspace.document;
  const project = document.project,
    cuts = project.tracks[0]?.segments ?? [];
  const [selected, setSelected] = useState(cuts[0]?.id ?? "");
  const [editError, setEditError] = useState<string>();
  const [showRecovery, setShowRecovery] = useState(false);
  const [mediaRefresh, setMediaRefresh] = useState(0);
  const media = useQuery(`project-media:${project.id}:${mediaRefresh}`, () =>
    loadProjectMedia(document, workspace.sources),
  );
  const context = useQuery(
    project.session_id ? `project-context:${project.session_id}` : null,
    async () => {
      const sid = project.session_id;
      if (!sid) return undefined;
      const [session, review, selection] = await Promise.all([
        getSession(sid),
        eventReview(sid),
        projectSelection(sid),
      ]);
      const fingerprint = JSON.stringify(
        session.assets.map((m) => [m.asset_id, m.duration_ms, m.overlap_with_previous_ms ?? 0]),
      );
      const digest = Array.from(
        new Uint8Array(
          await crypto.subtle.digest("SHA-256", new TextEncoder().encode(fingerprint)),
        ),
        (b) => b.toString(16).padStart(2, "0"),
      ).join("");
      if (digest !== review.layout_key || review.layout_key !== selection.layout_key)
        throw new Error("Session context changed. Refresh context to see current markers.");
      return { session, review };
    },
  );
  const rates = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(media.data ?? {}).flatMap(([id, m]) => {
          const rate = m.asset?.video?.average_frame_rate ?? m.asset?.video?.frame_rate;
          return rate ? [[id, rate]] : [];
        }),
      ),
    [media.data],
  );
  const timeline = useMemo(() => projectTimeline(document, rates), [document, rates]);
  const markers = useMemo(
    () => (context.data ? projectMarkers(document, context.data.session, context.data.review) : []),
    [document, context.data],
  );
  const v0 = useRef<HTMLVideoElement>(null),
    v1 = useRef<HTMLVideoElement>(null);
  const player = useRef<SessionPlayer | undefined>(undefined);
  const urls = useRef<Record<string, ProjectMedia>>({});
  urls.current = media.data ?? {};
  const [state, setState] = useState(initialPlayer);
  const audio = useRef(new EditorAudio());
  const playRequest = useRef(0);
  const lastMapping = useRef("");
  const lastMedia = useRef<unknown>(undefined);
  const [waiting, setWaiting] = useState(false);
  const drag = useRef<string | undefined>(undefined);
  const shortcuts = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!v0.current || !v1.current || !media.data) return;
    const mapping = JSON.stringify(timeline);
    if (player.current && mapping === lastMapping.current && media.data === lastMedia.current)
      return;
    lastMapping.current = mapping;
    lastMedia.current = media.data;
    if (!player.current)
      player.current = new SessionPlayer(
        timeline,
        [v0.current, v1.current],
        (id) => urls.current[id]?.url ?? "",
        setState,
      );
    else {
      player.current.pause();
      player.current.setTimeline(timeline);
    }
    setState(player.current.state);
  }, [timeline, media.data]);
  useEffect(
    () => () => {
      playRequest.current++;
      player.current?.pause();
      audio.current.close();
    },
    [],
  );
  useEffect(() => {
    const linear = audioAt(project.audio, state.virtualMs).linear;
    audio.current.apply(linear);
    if (linear > 1 && typeof AudioContext === "undefined" && player.current?.state.playing) {
      player.current.pause();
      setEditError("This preview cannot amplify audio. Choose gain at or below 0 dB.");
    }
  }, [project.audio, state.virtualMs]);
  useEffect(() => {
    if (!state.playing) return;
    let frame = requestAnimationFrame(function loop() {
      player.current?.tick();
      frame = requestAnimationFrame(loop);
    });
    return () => cancelAnimationFrame(frame);
  }, [state.playing]);
  const current = toSource(timeline, state.virtualMs);
  const currentMedia = current ? media.data?.[current.segment.assetId] : undefined;
  const canPlay = Boolean(currentMedia?.url && timeline.durationMs > 0);
  useEffect(() => {
    if (!canPlay) player.current?.pause();
  }, [canPlay]);
  const cut = cuts.find((c) => c.id === selected) ?? cuts[0];
  const cutIndex = cut ? cuts.indexOf(cut) : -1;
  const seek = (ms: number) => {
    playRequest.current++;
    player.current?.pause();
    player.current?.seek(ms);
  };
  const togglePlayback = () => {
    if (!canPlay) return;
    const token = ++playRequest.current;
    if (player.current?.state.playing) {
      player.current.pause();
      return;
    }
    const elements = [v0.current, v1.current].filter((v): v is HTMLVideoElement => v !== null);
    audio.current.apply(
      audioAt(workspace.document.project.audio, player.current?.virtualMs ?? 0).linear,
    );
    void audio.current
      .start(elements)
      .then(() => {
        if (token === playRequest.current) player.current?.play();
      })
      .catch((e) =>
        setEditError(e instanceof Error ? e.message : "Audio preview could not start."),
      );
  };
  const perform = (action: () => void) => {
    try {
      action();
      setEditError(undefined);
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "This change could not be applied.");
    }
  };
  const split = (offset: number) => {
    if (!cut) return;
    if (
      !Number.isSafeInteger(offset) ||
      offset <= 0 ||
      offset >= cut.source_out_ms - cut.source_in_ms
    ) {
      setEditError("Split inside the selected cut, between its first and last millisecond.");
      return;
    }
    const id = newSegmentId();
    perform(() => workspace.execute({ kind: "split", id: cut.id, at_ms: offset, new_id: id }));
  };
  const move = (id: string, target: number) => {
    const order = cuts.map((c) => c.id),
      old = order.indexOf(id);
    if (old < 0 || target < 0 || target >= order.length) return;
    order.splice(old, 1);
    order.splice(target, 0, id);
    perform(() => workspace.execute({ kind: "reorder", ids: order }));
  };
  const keydown = (e: KeyboardEvent<HTMLElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest("input,textarea,select,[contenteditable=true]")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      perform(() => (e.shiftKey ? workspace.redo() : workspace.undo()));
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      void workspace.flush().catch(() => undefined);
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (target.tagName === "BUTTON" && (e.key === " " || e.key === "Enter")) return;
    const actions: Record<string, () => void> = {
      " ": () => {
        togglePlayback();
      },
      k: () => {
        togglePlayback();
      },
      ",": () => player.current?.step(-1),
      ".": () => player.current?.step(1),
      "[": () => seek(nearestBoundary(timeline, state.virtualMs, -1)),
      "]": () => seek(nearestBoundary(timeline, state.virtualMs, 1)),
      Home: () => seek(0),
      End: () => seek(timeline.durationMs),
      s: () => split(state.virtualMs - (cut?.timeline_start_ms ?? 0)),
      Delete: () => {
        if (cut) perform(() => workspace.execute({ kind: "delete", id: cut.id }));
      },
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  };
  const retryMedia = async () => {
    try {
      await workspace.refreshSources();
      setMediaRefresh((n) => n + 1);
      setEditError(undefined);
    } catch (e) {
      setEditError(describeError(toApiError(e)));
    }
  };
  const prepare = async (id: string) => {
    try {
      await prepareDerived(id, { proxy_policy: "always" });
      setEditError(
        "Playback preparation started. Refresh preview after the background job finishes.",
      );
    } catch (e) {
      setEditError(describeError(toApiError(e)));
    }
  };
  const props = (index: 0 | 1) => ({
    className: index === state.activeElement ? "session-video active" : "session-video",
    preload: "auto" as const,
    crossOrigin: "anonymous" as const,
    playsInline: true,
    "aria-hidden": index !== state.activeElement,
    onEnded: () => player.current?.ended(index),
    onLoadedMetadata: () => {
      if (index === state.activeElement) player.current?.seek(player.current.virtualMs);
    },
    onTimeUpdate: () => {
      if (index === state.activeElement && state.playing) player.current?.tick();
    },
    onError: () =>
      player.current?.failed(index, "This source could not be played. Your edits are kept."),
    onWaiting: () => {
      if (index === state.activeElement) setWaiting(true);
    },
    onPlaying: () => setWaiting(false),
    onSeeked: () => setWaiting(false),
  });
  const pointerSeek = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button")) return;
    const bounds = e.currentTarget.getBoundingClientRect();
    if (bounds.width > 0)
      seek(Math.round(((e.clientX - bounds.left) / bounds.width) * timeline.durationMs));
  };
  const selectedSource = document.sources.find((s) => s.asset_id === cut?.asset_id);
  const ratio = document.layout.aspect_ratio.replace(":", " / ");
  const sourceSize = (m: ProjectMedia | undefined): [number, number] => {
    const v = m?.asset?.video;
    if (!v) return [1920, 1080];
    return v.rotation === 90 || v.rotation === 270 ? [v.height, v.width] : [v.width, v.height];
  };
  const [previewWidth, previewHeight] = sourceSize(currentMedia);
  const [cutWidth, cutHeight] = sourceSize(cut ? media.data?.[cut.asset_id] : undefined);
  return (
    <section
      className="view editor"
      aria-labelledby="editor-heading"
      onKeyDown={keydown}
      tabIndex={-1}
    >
      <div className="editor-heading">
        <div>
          <a href="#/projects">← Projects</a>
          <p className="eyebrow">STORY EDITOR</p>
          <h1 id="editor-heading">{project.title}</h1>
        </div>
        <div className="editor-save">
          <span
            role="status"
            aria-label="Project save status"
            className={`save-status ${workspace.status}`}
          >
            {workspace.status === "saved"
              ? `Saved · revision ${workspace.autosave.revision}`
              : workspace.status === "saving"
                ? "Saving…"
                : workspace.status === "error"
                  ? "Not saved · edits kept in this window"
                  : "Unsaved changes"}
          </span>
          <button
            disabled={workspace.status === "saved" || !workerReady}
            onClick={() => void workspace.flush().catch(() => undefined)}
          >
            Save now
          </button>
        </div>
      </div>
      {!workerReady && (
        <p role="alert" className="notice-box">
          Worker offline. You can keep editing; this window keeps your draft. Save before reloading.
        </p>
      )}
      {workspace.error && (
        <div className="notice-box" role="alert">
          <p>{describeError(workspace.error)} Your draft has not been discarded.</p>
          <button
            disabled={!workerReady}
            onClick={() => void workspace.flush().catch(() => undefined)}
          >
            Retry save
          </button>
          <button onClick={() => setShowRecovery(true)}>Show recovery JSON</button>
        </div>
      )}
      {editError && (
        <p role="alert" className="notice-box">
          {editError}
        </p>
      )}
      <div className="editor-toolbar" role="toolbar" aria-label="Editing commands">
        <button
          disabled={!workspace.history.canUndo}
          onClick={() => perform(() => workspace.undo())}
        >
          Undo
        </button>
        <button
          disabled={!workspace.history.canRedo}
          onClick={() => perform(() => workspace.redo())}
        >
          Redo
        </button>
        <label>
          Selected cut
          <select
            aria-label="Selected cut"
            value={cut?.id ?? ""}
            disabled={!cut}
            onChange={(e) => {
              const selectedCut = cuts.find((s) => s.id === e.target.value);
              if (selectedCut) {
                setSelected(selectedCut.id);
                seek(selectedCut.timeline_start_ms);
              }
            }}
          >
            {cuts.map((s, i) => (
              <option key={s.id} value={s.id}>
                Cut {i + 1} · {formatClock(s.source_out_ms - s.source_in_ms)}
              </option>
            ))}
          </select>
        </label>
        <span className="toolbar-divider" />
        <label>
          Preview frame
          <select
            aria-label="Preview aspect ratio"
            value={document.layout.aspect_ratio}
            onChange={(e) =>
              perform(() =>
                workspace.execute({
                  kind: "settings",
                  layout: {
                    ...document.layout,
                    aspect_ratio: e.target.value as "16:9" | "9:16" | "1:1",
                  },
                }),
              )
            }
          >
            <option>16:9</option>
            <option>9:16</option>
            <option>1:1</option>
          </select>
        </label>
        <button onClick={() => setShowRecovery((v) => !v)}>Recovery JSON</button>
        <button
          type="button"
          aria-controls="editor-shortcuts"
          onClick={() => {
            if (shortcuts.current) {
              shortcuts.current.open = true;
              shortcuts.current.querySelector("summary")?.focus();
              shortcuts.current.scrollIntoView?.({ block: "nearest" });
            }
          }}
        >
          Keyboard help
        </button>
      </div>
      <div className="editor-grid">
        <div className="editor-preview-column">
          <div className="editor-stage">
            <div
              className="editor-frame"
              style={{ aspectRatio: ratio }}
              data-aspect={document.layout.aspect_ratio}
              role="group"
              aria-label="Project preview"
            >
              <video ref={v0} {...props(0)} />
              <video ref={v1} {...props(1)} />
              {(document.layout.aspect_ratio === "9:16" ||
                project.overlays.some((o) => o.kind === "blur")) && (
                <VerticalPreview
                  aspectRatio={document.layout.aspect_ratio}
                  blurs={project.overlays.filter((o) => o.kind === "blur")}
                  video={state.activeElement === 0 ? v0 : v1}
                  cut={cuts.find((c) => c.id === current?.segment.key)}
                  width={previewWidth}
                  height={previewHeight}
                  atMs={state.virtualMs}
                  playing={state.playing}
                />
              )}
              <CaptionPreview document={document} atMs={state.virtualMs} />
              {!canPlay && (
                <div className="player-empty">
                  {cuts.length === 0
                    ? "This story is empty. Undo to restore a cut."
                    : media.loading
                      ? "Loading source preview…"
                      : (currentMedia?.reason ?? "Preview unavailable. Your edits are kept.")}
                </div>
              )}
              {waiting && state.playing && (
                <span className="player-loading" role="status">
                  Buffering…
                </span>
              )}
            </div>
          </div>
          <p className="muted">
            Vertical crops, privacy blur geometry, caption placement and audio edits are previewed.
            Blur appearance is approximate; verify the rendered file. Blurs do not remove caption or
            exported metadata text. Text overlays appear only in supported exports.
          </p>
          {state.error && <p role="alert">{state.error}</p>}
          <div className="transport">
            <button disabled={!canPlay} onClick={togglePlayback}>
              {state.playing ? "Pause" : "Play"}
            </button>
            <button
              disabled={!canPlay}
              onClick={() => player.current?.step(-1)}
              aria-label="Previous project frame"
            >
              ◀ Frame
            </button>
            <button
              disabled={!canPlay}
              onClick={() => player.current?.step(1)}
              aria-label="Next project frame"
            >
              Frame ▶
            </button>
            <button onClick={() => seek(nearestBoundary(timeline, state.virtualMs, -1))}>
              Previous cut
            </button>
            <button onClick={() => seek(nearestBoundary(timeline, state.virtualMs, 1))}>
              Next cut
            </button>
            <output className="clock" aria-label="Project time" aria-live="off">
              {formatClock(state.virtualMs)} / {formatClock(timeline.durationMs)}
            </output>
          </div>
          <input
            type="range"
            className="scrub"
            min={0}
            max={timeline.durationMs}
            step={1}
            value={state.virtualMs}
            aria-label="Project position"
            onChange={(e) => seek(Number(e.target.value))}
            disabled={cuts.length === 0}
          />
          <label className="position-number">
            Go to project time (ms)
            <input
              type="number"
              min={0}
              max={timeline.durationMs}
              step={1}
              value={state.virtualMs}
              onChange={(e) => seek(Number(e.target.value))}
            />
          </label>
          <p className="source-time muted" aria-live="off">
            {current
              ? `Cut ${current.segment.index + 1}: ${currentMedia?.asset?.original_name ?? document.sources.find((s) => s.asset_id === current.segment.assetId)?.original_name ?? "Source"} at ${formatClock(current.sourceMs)} · ${currentMedia?.usesProxy ? "playback copy" : "original"}`
              : "No source selected"}
          </p>
          <div className="row">
            <button disabled={!workerReady} onClick={() => void retryMedia()}>
              Refresh preview
            </button>
            {current && !currentMedia?.usesProxy && (
              <button disabled={!workerReady} onClick={() => void prepare(current.segment.assetId)}>
                Prepare playback copy
              </button>
            )}
            <a href="#/library">Restore missing originals in Library</a>
          </div>
        </div>
        {cut && (
          <CutInspector
            key={cut.id}
            cut={cut}
            index={cutIndex}
            count={cuts.length}
            sourceDuration={selectedSource?.duration_ms ?? cut.source_out_ms}
            playhead={state.virtualMs}
            onTrim={(from, to) => {
              if (
                !Number.isSafeInteger(from) ||
                !Number.isSafeInteger(to) ||
                from < 0 ||
                from >= to ||
                to > (selectedSource?.duration_ms ?? 0)
              ) {
                setEditError("Choose whole milliseconds with 0 ≤ in < out ≤ source duration.");
                return;
              }
              perform(() =>
                workspace.execute({
                  kind: "trim",
                  id: cut.id,
                  source_in_ms: from,
                  source_out_ms: to,
                }),
              );
            }}
            onMove={(by) => move(cut.id, cutIndex + by)}
            onRemove={() => perform(() => workspace.execute({ kind: "delete", id: cut.id }))}
            onSplit={split}
          />
        )}
      </div>
      <section className="editor-timeline panel" aria-labelledby="timeline-heading">
        <div className="view-head">
          <h2 id="timeline-heading">Primary track</h2>
          <span className="muted">
            {cuts.length} cuts · {formatClock(timeline.durationMs)}
          </span>
        </div>
        <div className="editor-track-scroll">
          <div
            className="editor-lane"
            style={{ width: `max(100%, ${cuts.length * 160}px)` }}
            onPointerDown={pointerSeek}
          >
            {cuts.map((s, i) => {
              const m = media.data?.[s.asset_id],
                segment = timeline.segments[i];
              const thumbs = (m?.filmstrip ?? [])
                .map((t, n) => ({ t, n: n + 1 }))
                .filter((f) => f.t >= s.source_in_ms && f.t < s.source_out_ms);
              return (
                <div
                  className={`editor-cut ${cut?.id === s.id ? "selected" : ""}`}
                  key={s.id}
                  style={{
                    width: `${((s.source_out_ms - s.source_in_ms) / Math.max(1, timeline.durationMs)) * 100}%`,
                  }}
                  draggable
                  onDragStart={(e) => {
                    drag.current = s.id;
                    setSelected(s.id);
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", s.id);
                  }}
                  onDragEnd={() => {
                    drag.current = undefined;
                  }}
                  onDragOver={(e) => {
                    if (drag.current) e.preventDefault();
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (drag.current) move(drag.current, i);
                    drag.current = undefined;
                  }}
                >
                  <button
                    className="cut-select"
                    aria-pressed={cut?.id === s.id}
                    onClick={() => {
                      setSelected(s.id);
                      seek(s.timeline_start_ms);
                    }}
                  >
                    <span className="cut-number">{String(i + 1).padStart(2, "0")}</span>
                    <strong>
                      {m?.asset?.original_name ??
                        document.sources.find((a) => a.asset_id === s.asset_id)?.original_name ??
                        "Missing source"}
                    </strong>
                    <span>
                      {formatClock(s.timeline_start_ms)} ·{" "}
                      {formatClock(s.source_out_ms - s.source_in_ms)}
                    </span>
                  </button>
                  <div className="cut-thumbnails" aria-hidden="true">
                    {thumbs.slice(0, 8).map((f) => (
                      <img key={f.n} src={thumbnailUrl(s.asset_id, f.n)} alt="" loading="lazy" />
                    ))}
                  </div>
                  {segment && m?.waveform && (
                    <SegmentWave segment={segment} durationMs={timeline.durationMs} />
                  )}
                  {project.audio.mute_ranges.flatMap((range, n) => {
                    const start = Math.max(s.timeline_start_ms, range.start_ms),
                      end = Math.min(
                        s.timeline_start_ms + s.source_out_ms - s.source_in_ms,
                        range.end_ms,
                      );
                    return start < end
                      ? [
                          <span
                            key={n}
                            className="cut-muted"
                            title={`Muted ${start}–${end} ms`}
                            style={{
                              left: `${((start - s.timeline_start_ms) / (s.source_out_ms - s.source_in_ms)) * 100}%`,
                              width: `${((end - start) / (s.source_out_ms - s.source_in_ms)) * 100}%`,
                            }}
                          >
                            Muted
                          </span>,
                        ]
                      : [];
                  })}
                  <span className="cut-source-range">
                    Source {formatClock(s.source_in_ms)} → {formatClock(s.source_out_ms)}
                  </span>
                </div>
              );
            })}
            <span
              className="track-head"
              style={{ left: `${(state.virtualMs / Math.max(1, timeline.durationMs)) * 100}%` }}
            />
          </div>
        </div>
        <p className="muted">
          Select a cut to trim it. Drag cuts to reorder, or use Move earlier / later. Source
          boundaries stay visible.
        </p>
        {markers.length > 0 && (
          <div className="event-marker-track" aria-label="Read-only event markers">
            {markers.map((m) => (
              <button
                key={m.key}
                className="event-marker"
                style={{ left: `${(m.atMs / Math.max(1, timeline.durationMs)) * 100}%` }}
                title={`${m.label}: ${m.detail}`}
                onClick={() => seek(m.atMs)}
                aria-label={`Context: ${m.label} at ${formatClock(m.atMs)}`}
              >
                ◆
              </button>
            ))}
          </div>
        )}
        {context.data && (
          <p className="muted">
            Read-only session context ·{" "}
            {context.data.review.total === 0
              ? "No detected events"
              : `${Math.min(50, context.data.review.items.length)} of ${context.data.review.total} events inspected`}
            . Edits never change events.
          </p>
        )}
        {context.error && (
          <p role="status">
            Event context unavailable. Editing still works.{" "}
            <button onClick={context.refetch}>Refresh context</button>
          </p>
        )}
      </section>
      <div className="editor-detail-panels">
        <LayoutPanel
          document={document}
          cut={cut}
          width={cutWidth}
          height={cutHeight}
          atMs={state.virtualMs}
          onCommand={(command) => perform(() => workspace.execute(command))}
          seek={seek}
        />
        <CaptionPanel
          workspace={workspace}
          atMs={state.virtualMs}
          sourceAspect={(() => {
            const v = currentMedia?.asset?.video;
            if (!v) return 16 / 9;
            return v.rotation === 90 || v.rotation === 270
              ? v.height / v.width
              : v.width / v.height;
          })()}
          onCommand={(command: EditorCommand) => perform(() => workspace.execute(command))}
          seek={seek}
        />
        <AudioPanel
          document={document}
          cut={cut}
          atMs={state.virtualMs}
          onCommand={(command: EditorCommand) => perform(() => workspace.execute(command))}
        />
      </div>
      <PrivacyPanel
        workspace={workspace}
        atMs={state.virtualMs}
        seek={seek}
        onCommand={(c) => perform(() => workspace.execute(c))}
      />
      <ExportPanel
        projectId={project.id}
        document={document}
        flush={async () => {
          await workspace.flush();
          return workspace.autosave.revision;
        }}
        workerReady={workerReady}
        media={media.data}
      />
      {showRecovery && (
        <section className="panel" aria-labelledby="recovery-heading">
          <h2 id="recovery-heading">Recovery JSON</h2>
          <p>
            Select and copy this complete local draft before reloading if saving is unavailable.
          </p>
          <textarea
            aria-label="Unsaved project JSON"
            readOnly
            rows={8}
            value={JSON.stringify(document, null, 2)}
            onFocus={(e) => e.currentTarget.select()}
          />
        </section>
      )}
      <details ref={shortcuts} className="shortcuts panel" id="editor-shortcuts">
        <summary>Editor keyboard shortcuts</summary>
        <p>
          Space / K play or pause · , / . previous / next frame · [ / ] previous / next cut · Home /
          End start / end · S split selected cut at playhead · Delete remove selected cut · Ctrl/⌘ Z
          undo · Ctrl/⌘ Shift Z redo · Ctrl/⌘ S save.
        </p>
        <p>
          Shortcuts are inactive in text and numeric fields. Every edit also has a labelled button
          or numeric field. Originals are never modified.
        </p>
      </details>
      <p className="muted">
        Frame stepping uses{" "}
        {Math.round(frameMs(current ? timeline.members[current.segment.index] : undefined) * 100) /
          100}{" "}
        ms from the source frame rate; variable-frame-rate footage uses its average.
      </p>
    </section>
  );
}
