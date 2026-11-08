// SPDX-License-Identifier: AGPL-3.0-or-later
import { load, type EditorProject } from "@openworld-moments/contracts";

export interface SavedProject {
  document: EditorProject;
  revision: number;
}
export type SaveProject = (
  document: EditorProject,
  expectedRevision: number,
) => Promise<SavedProject>;

/** 750 ms trailing debounce, serialized CAS saves, explicit close flush and discard.
 * Failure keeps the dirty document; retry requires flush() or another edit.
 * Never retry a revision conflict automatically. A caller can recover/export dirty state.
 */
export class ProjectAutosave {
  #pending: EditorProject | undefined;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #running: Promise<void> | undefined;
  #revision: number;
  #closed = false;
  #discarded = false;
  error: unknown;
  constructor(
    readonly save: SaveProject,
    revision: number,
    readonly delayMs = 750,
  ) {
    if (!Number.isSafeInteger(revision) || revision < 0 || !Number.isFinite(delayMs) || delayMs < 0)
      throw new Error("Invalid autosave configuration");
    this.#revision = revision;
  }
  get dirty(): boolean {
    return this.#pending !== undefined || this.#running !== undefined;
  }
  get revision(): number {
    return this.#revision;
  }
  get pending(): EditorProject | undefined {
    return this.#pending && structuredClone(this.#pending);
  }
  schedule(document: EditorProject): void {
    if (this.#closed) throw new Error("Autosave is closed");
    this.#pending = structuredClone(load("editor-project", document));
    clearTimeout(this.#timer);
    this.#timer = setTimeout(() => {
      void this.flush().catch(() => {
        /* error remains observable */
      });
    }, this.delayMs);
  }
  async flush(): Promise<void> {
    clearTimeout(this.#timer);
    if (this.#running) {
      await this.#running;
      if (this.#pending) return this.flush();
      return;
    }
    if (!this.#pending) return;
    const document = this.#pending;
    this.#pending = undefined;
    this.#running = (async () => {
      try {
        const saved = await this.save(structuredClone(document), this.#revision);
        this.#revision = saved.revision;
        this.error = undefined;
      } catch (error) {
        if (!this.#discarded) this.#pending ??= document;
        this.error = error;
        throw error;
      }
    })();
    try {
      await this.#running;
    } finally {
      this.#running = undefined;
    }
    if (this.#pending) await this.flush();
  }
  async close(): Promise<void> {
    this.#closed = true;
    await this.flush();
  }
  /** Explicitly discard unsaved edits. Does not cancel a save already submitted. */
  discard(): void {
    clearTimeout(this.#timer);
    this.#pending = undefined;
    this.#closed = true;
    this.#discarded = true;
  }
}
