// SPDX-License-Identifier: AGPL-3.0-or-later
import { open } from "@tauri-apps/plugin-dialog";
import { useId, useRef, useState } from "react";
import { describeError, type ImportMode, startImport } from "./api";
import { upsertJob } from "./jobs";
import { useDialogFocus } from "./a11y";
import { useAction } from "./query";

const VIDEO_EXTENSIONS = ["mp4", "m4v", "mov", "mkv", "webm", "ts", "m2ts", "avi"];
const MODE_KEY = "owm.import.mode";

export function savedMode(): ImportMode {
  try {
    return window.localStorage.getItem(MODE_KEY) === "managed" ? "managed" : "reference";
  } catch {
    return "reference";
  }
}

export function saveMode(mode: ImportMode): void {
  try {
    window.localStorage.setItem(MODE_KEY, mode);
  } catch {
    // Storage can be unavailable; the default applies next time.
  }
}

function asList(choice: string | string[] | null): string[] {
  if (choice === null) return [];
  return Array.isArray(choice) ? choice : [choice];
}

function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/**
 * Import dialog: pick files or a folder (or receive dropped paths), choose how the
 * library keeps them, start an import job. Originals are never moved or changed.
 */
export function ImportPanel({
  initialPaths = [],
  droppedPaths,
  onClose,
  onStarted,
}: {
  initialPaths?: string[];
  droppedPaths?: string[];
  onClose: () => void;
  onStarted: () => void;
}) {
  const [selection, setSelection] = useState({
    drop: droppedPaths,
    paths: [...new Set([...initialPaths, ...(droppedPaths ?? [])])],
  });
  const paths = selection.paths;
  const merge = (existing: string[], incoming: string[]) => [
    ...new Set([...existing, ...incoming]),
  ];
  const [mode, setMode] = useState<ImportMode>(savedMode);
  const headingId = useId();
  const firstButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const submit = useAction(async () => {
    const job = await startImport(paths, mode);
    upsertJob(job);
  });

  if (selection.drop !== droppedPaths) {
    setSelection({
      drop: droppedPaths,
      paths: submit.busy ? paths : merge(paths, droppedPaths ?? []),
    });
  }
  useDialogFocus(
    dialog,
    () => {
      if (!submit.busy) onClose();
    },
    firstButton,
  );

  const picker = useAction(async (directory: boolean) => {
    const choice = await open({
      directory,
      multiple: true,
      title: directory ? "Choose folders to import" : "Choose video files to import",
      ...(directory ? {} : { filters: [{ name: "Video", extensions: VIDEO_EXTENSIONS }] }),
    });
    const picked = asList(choice);
    if (picked.length) {
      setSelection((current) => ({ ...current, paths: merge(current.paths, picked) }));
    }
  });

  async function start() {
    saveMode(mode);
    if (await submit.run()) {
      onStarted();
      onClose();
    }
  }

  return (
    <div className="overlay">
      <section
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="dialog import-dialog"
      >
        <h2 id={headingId}>Import media</h2>
        <p className="muted">
          Choose video files or folders. Folders are searched for supported videos, including
          subfolders.
        </p>
        <div className="import-dropzone">
          <span className="feature-icon" aria-hidden="true">
            ↑
          </span>
          <strong>Drop files or folders here</strong>
          <div className="row center">
            <button
              type="button"
              ref={firstButton}
              disabled={picker.busy || submit.busy}
              onClick={() => void picker.run(false)}
            >
              Choose files…
            </button>
            <button
              type="button"
              disabled={picker.busy || submit.busy}
              onClick={() => void picker.run(true)}
            >
              Choose folder…
            </button>
          </div>
        </div>
        {picker.error && <p role="alert">{describeError(picker.error)}</p>}
        {paths.length > 0 ? (
          <ul className="paths" aria-label="Selected for import">
            {paths.map((path) => (
              <li key={path}>
                <span title={path}>{baseName(path)}</span>
                <button
                  type="button"
                  className="link"
                  aria-label={`Remove ${baseName(path)} from the selection`}
                  disabled={submit.busy}
                  onClick={() =>
                    setSelection((current) => ({
                      ...current,
                      paths: current.paths.filter((item) => item !== path),
                    }))
                  }
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Nothing selected yet. You can also drop files onto the window.</p>
        )}
        <fieldset disabled={submit.busy}>
          <legend>How should the library keep them?</legend>
          <label>
            <input
              type="radio"
              name="import-mode"
              value="reference"
              checked={mode === "reference"}
              onChange={() => setMode("reference")}
            />{" "}
            Keep files where they are (reference)
          </label>
          <label>
            <input
              type="radio"
              name="import-mode"
              value="managed"
              checked={mode === "managed"}
              onChange={() => setMode("managed")}
            />{" "}
            Copy into the library (managed)
          </label>
          <p className="muted">
            Either way, your original files are never moved, changed, or deleted.
          </p>
        </fieldset>
        {submit.error && <p role="alert">Import could not start: {describeError(submit.error)}</p>}
        <div className="row end">
          <button type="button" onClick={onClose} disabled={submit.busy}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            disabled={paths.length === 0 || submit.busy || picker.busy}
            onClick={() => void start()}
          >
            {submit.busy ? "Starting…" : `Import ${paths.length || ""}`.trim()}
          </button>
        </div>
      </section>
    </div>
  );
}
