// SPDX-License-Identifier: AGPL-3.0-or-later
import { load, type EditorProject } from "@openworld-moments/contracts";
import { getProject, saveProject, toApiError, type ApiError, type ProjectState } from "./api";
import { EditorHistory, type EditorCommand } from "./editor";
import { invalidate } from "./query";
import { ProjectAutosave } from "./projectAutosave";

/** Keeps dirty work alive across hash navigation and worker restarts in this window. */
export class ProjectWorkspace {
  readonly history: EditorHistory;
  private current: EditorProject;
  readonly autosave: ProjectAutosave;
  private listeners = new Set<() => void>();
  private version = 0;
  private generation = 0;
  status: "saved" | "unsaved" | "saving" | "error" = "saved";
  error: ApiError | undefined;
  sources: NonNullable<ProjectState["sources"]>;
  constructor(state: ProjectState) {
    this.history = new EditorHistory(load("editor-project", state.document));
    this.current = this.history.document;
    freeze(this.current);
    this.sources = state.sources ?? [];
    this.autosave = new ProjectAutosave(async (document, revision) => {
      const generation = this.generation;
      this.status = "saving";
      this.emit();
      try {
        const saved = await saveProject(document, revision);
        this.status = generation === this.generation ? "saved" : "unsaved";
        this.error = undefined;
        invalidate("projects");
        return saved;
      } catch (error) {
        this.error = toApiError(error);
        this.status = "error";
        throw error;
      } finally {
        setTimeout(() => this.emit(), 0);
      }
    }, state.revision);
  }
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  snapshot = (): number => this.version;
  private emit(): void {
    this.version++;
    for (const listener of this.listeners) listener();
    changedWorkspaces();
  }
  get document(): EditorProject {
    return this.current;
  }
  private changed(document: EditorProject): void {
    freeze(document);
    this.current = document;
    this.generation++;
    this.status = "unsaved";
    this.autosave.schedule(document);
    this.emit();
  }
  execute(command: EditorCommand): void {
    this.changed(this.history.execute(command));
  }
  undo(): void {
    if (this.history.canUndo) this.changed(this.history.undo());
  }
  redo(): void {
    if (this.history.canRedo) this.changed(this.history.redo());
  }
  async flush(): Promise<void> {
    try {
      await this.autosave.flush();
    } finally {
      this.emit();
    }
  }
  async refreshSources(): Promise<void> {
    const state = await getProject(this.document.project.id);
    // Do not overwrite local edits or a revision conflict with a fetched document.
    if (state.revision !== this.autosave.revision)
      throw new Error(
        "The saved project changed. Your local edits are kept; copy recovery JSON before reopening.",
      );
    this.sources = state.sources ?? [];
    this.emit();
  }
}

function freeze(value: unknown): void {
  if (value && typeof value === "object") {
    Object.freeze(value);
    for (const child of Object.values(value)) freeze(child);
  }
}

let workspaceVersion = 0;
const workspaceListeners = new Set<() => void>();
function changedWorkspaces(): void {
  workspaceVersion++;
  for (const listener of workspaceListeners) listener();
}
export const workspaceSnapshot = (): number => workspaceVersion;
export const subscribeWorkspaces = (listener: () => void): (() => void) => {
  workspaceListeners.add(listener);
  return () => workspaceListeners.delete(listener);
};

const workspaces = new Map<string, ProjectWorkspace>();
const opening = new Map<string, Promise<ProjectWorkspace>>();
export function openWorkspace(id: string): Promise<ProjectWorkspace> {
  const known = workspaces.get(id);
  if (known) return Promise.resolve(known);
  const pending = opening.get(id);
  if (pending) return pending;
  // Bound clean retained histories; dirty drafts are never silently evicted.
  if (workspaces.size + opening.size >= 10) {
    const clean = [...workspaces].find(([, w]) => !w.autosave.dirty);
    if (clean) workspaces.delete(clean[0]);
    else
      return Promise.reject(
        new Error("Save or copy your open drafts before opening another project."),
      );
  }
  const request = getProject(id)
    .then((state) => {
      const workspace = new ProjectWorkspace(state);
      workspaces.set(id, workspace);
      changedWorkspaces();
      return workspace;
    })
    .finally(() => opening.delete(id));
  opening.set(id, request);
  return request;
}
export function dirtyProjects(): { id: string; title: string }[] {
  return [...workspaces]
    .filter(([, w]) => w.autosave.dirty)
    .map(([id, w]) => ({ id, title: w.document.project.title }));
}
export function hasUnsavedProjects(): boolean {
  return dirtyProjects().length > 0;
}
/** Test cleanup only. Production leaves dirty drafts intact across navigation. */
export function resetWorkspaces(): void {
  for (const w of workspaces.values()) w.autosave.discard();
  workspaces.clear();
  opening.clear();
}
