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
  initialPaths,
  onClose,
  onStarted,
}: {
  initialPaths: string[];
  onClose: () => void;
  onStarted: () => void;
}) {
  const [paths, setPaths] = useState<string[]>(initialPaths);
  const [mode, setMode] = useState<ImportMode>(savedMode);
  const headingId = useId();
  const firstButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const submit = useAction(async () => {
    const job = await startImport(paths, mode);
    upsertJob(job);
  });

  useDialogFocus(dialog, onClose, firstButton);

  async function choose(directory: boolean) {
    const choice = await open({
      directory,
      multiple: true,
      title: directory ? "Choose folders to import" : "Choose video files to import",
      ...(directory ? {} : { filters: [{ name: "Video", extensions: VIDEO_EXTENSIONS }] }),
    });
    const picked = asList(choice);
    if (picked.length) setPaths((current) => [...new Set([...current, ...picked])]);
  }

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
        className="dialog"
      >
        <h2 id={headingId}>Import media</h2>
        <p className="muted">
          Choose video files or folders. Folders are searched for supported videos, including
          subfolders.
        </p>
        <div className="row">
          <button type="button" ref={firstButton} onClick={() => void choose(false)}>
            Choose files…
          </button>
          <button type="button" onClick={() => void choose(true)}>
            Choose folder…
          </button>
        </div>
        {paths.length > 0 ? (
          <ul className="paths" aria-label="Selected for import">
            {paths.map((path) => (
              <li key={path}>
                <span title={path}>{baseName(path)}</span>
                <button
                  type="button"
                  className="link"
                  aria-label={`Remove ${baseName(path)} from the selection`}
                  onClick={() => setPaths((current) => current.filter((p) => p !== path))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Nothing selected yet. You can also drop files onto the window.</p>
        )}
        <fieldset>
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
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="primary"
            disabled={paths.length === 0 || submit.busy}
            onClick={() => void start()}
          >
            {submit.busy ? "Starting…" : `Import ${paths.length || ""}`.trim()}
          </button>
        </div>
      </section>
    </div>
  );
}
