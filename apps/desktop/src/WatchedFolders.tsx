// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useState } from "react";
import type { WatchedFile } from "@openworld-moments/contracts";
import {
  type SourceKind,
  type WatchedFolderView,
  addWatched,
  describeFolder,
  errorMessage,
  listWatched,
  parsePatterns,
  pickFolder,
  removeWatched,
  reauthorizeWatched,
  updateWatched,
  watchedFiles,
} from "./watched";

const SOURCES: { value: SourceKind; label: string }[] = [
  { value: "xbox", label: "Xbox (OneDrive)" },
  { value: "playstation", label: "PlayStation" },
  { value: "obs", label: "OBS" },
  { value: "capture_card", label: "Capture card" },
  { value: "other", label: "Other" },
];

export const POLL_MS = 5000;

type Load =
  | { status: "loading" }
  | { status: "ready"; views: WatchedFolderView[] }
  | { status: "error"; message: string };

/** Settings: the folders watched for new captures, their status, and their options. */
export function WatchedFolders({
  onChange,
  refreshKey = 0,
}: {
  onChange?: (views: WatchedFolderView[]) => void;
  /** Change it to reload now (e.g. after onboarding added a folder). */
  refreshKey?: number;
}) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [notice, setNotice] = useState<string | null>(null);
  const [source, setSource] = useState<SourceKind>("xbox");

  const refresh = useCallback(async () => {
    try {
      const views = await listWatched();
      setLoad({ status: "ready", views });
      onChange?.(views);
    } catch (error) {
      setLoad({ status: "error", message: errorMessage(error) });
    }
  }, [onChange]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      listWatched().then(
        (views) => {
          if (cancelled) return;
          setLoad({ status: "ready", views });
          onChange?.(views);
        },
        (error: unknown) => {
          if (!cancelled) setLoad({ status: "error", message: errorMessage(error) });
        },
      );
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [onChange, refreshKey]);

  async function run(action: () => Promise<unknown>, done: string) {
    setNotice(null);
    try {
      if ((await action()) !== false) setNotice(done);
    } catch (error) {
      setNotice(`Could not complete that: ${errorMessage(error)}`);
    }
    await refresh();
  }

  async function add() {
    const path = await pickFolder("Choose a folder to watch for captures");
    if (path === null) return;
    await run(() => addWatched(path, source), "Folder added. New captures will be imported.");
  }

  return (
    <section aria-labelledby="watched-heading" className="panel">
      <h2 id="watched-heading">Watched folders</h2>
      <p className="muted">
        New videos in these folders are imported once they finish copying. Files are never moved,
        changed, or deleted.
      </p>
      <div className="row">
        <label>
          Source{" "}
          <select value={source} onChange={(e) => setSource(e.target.value as SourceKind)}>
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void add()}>
          Add folder…
        </button>
      </div>
      {notice && (
        <p role="status" className="notice-line">
          {notice}
        </p>
      )}
      {load.status === "loading" && <p className="muted">Loading watched folders…</p>}
      {load.status === "error" && (
        <p role="alert">Watched folders are unavailable: {load.message}</p>
      )}
      {load.status === "ready" && load.views.length === 0 && (
        <p className="muted">
          No folders yet. Add the folder your captures are saved or synced to.
        </p>
      )}
      {load.status === "ready" && load.views.length > 0 && (
        <ul className="folders">
          {load.views.map((view) => (
            <FolderItem key={view.folder.id} view={view} run={run} />
          ))}
        </ul>
      )}
    </section>
  );
}

function FolderItem({
  view,
  run,
}: {
  view: WatchedFolderView;
  run: (action: () => Promise<unknown>, done: string) => Promise<void>;
}) {
  const { folder } = view;
  const [include, setInclude] = useState(folder.include.join(", "));
  const [exclude, setExclude] = useState(folder.exclude.join(", "));
  const [failures, setFailures] = useState<WatchedFile[] | null>(null);
  const id = `folder-${folder.id}`;

  async function showFailures() {
    try {
      const files = await watchedFiles(folder.id);
      setFailures(files.filter((f) => f.state === "failed"));
    } catch {
      setFailures([]);
    }
  }

  async function restoreAccess() {
    // Cancellation is not a successful reauthorization and changes no settings.
    await run(
      () => reauthorizeWatched(folder.id),
      "Folder check finished. Its import history was kept.",
    );
  }

  return (
    <li className="folder" aria-labelledby={`${id}-path`}>
      <p id={`${id}-path`} className="path">
        {folder.path}
      </p>
      <p className="muted" data-testid={`${id}-status`}>
        {describeFolder(view)}
      </p>
      <div className="row">
        <label>
          <input
            type="checkbox"
            checked={folder.enabled}
            onChange={(e) =>
              void run(
                () => updateWatched(folder.id, { enabled: e.target.checked }),
                e.target.checked ? "Watching resumed." : "Watching paused.",
              )
            }
          />{" "}
          Watch this folder
        </label>
        <label>
          <input
            type="checkbox"
            checked={folder.recursive}
            onChange={(e) =>
              void run(
                () => updateWatched(folder.id, { recursive: e.target.checked }),
                "Subfolder setting saved.",
              )
            }
          />{" "}
          Include subfolders
        </label>
      </div>
      <details>
        <summary>File filters</summary>
        <label className="field">
          Only import files matching (comma-separated, empty = all videos)
          <input value={include} onChange={(e) => setInclude(e.target.value)} />
        </label>
        <label className="field">
          Skip files matching
          <input value={exclude} onChange={(e) => setExclude(e.target.value)} />
        </label>
        <button
          type="button"
          onClick={() =>
            void run(
              () =>
                updateWatched(folder.id, {
                  include: parsePatterns(include),
                  exclude: parsePatterns(exclude),
                }),
              "Filters saved.",
            )
          }
        >
          Save filters
        </button>
      </details>
      <div className="row">
        {(view.status?.state === "unavailable" || folder.availability === "unavailable") && (
          <button type="button" onClick={() => void restoreAccess()}>
            Select folder again…
          </button>
        )}
        {folder.stats.failed > 0 && (
          <button type="button" onClick={() => void showFailures()}>
            Show failed files
          </button>
        )}
        <button
          type="button"
          onClick={() =>
            void run(
              () => removeWatched(folder.id),
              "Stopped watching. The folder and its files were not changed.",
            )
          }
        >
          Stop watching
        </button>
      </div>
      {failures !== null && (
        <ul className="failures" aria-label="Failed files">
          {failures.length === 0 && <li>No failed files.</li>}
          {failures.map((f) => (
            <li key={f.relative_path}>
              {f.relative_path}: {f.error?.message ?? "Import failed."}
              {f.retry_at ? " Will retry automatically." : ""}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
