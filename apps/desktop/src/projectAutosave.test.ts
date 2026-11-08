// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, expect, it, vi } from "vitest";
import { load, type EditorProject } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { ProjectAutosave } from "./projectAutosave";
const doc = (title: string): EditorProject => {
  const d = structuredClone(load("editor-project", fixture));
  d.project.title = title;
  return d;
};
afterEach(() => vi.useRealTimers());
it("debounces to latest edit and flushes on close", async () => {
  vi.useFakeTimers();
  const save = vi.fn(async (document: EditorProject, revision: number) => ({
    document,
    revision: revision + 1,
  }));
  const a = new ProjectAutosave(save, 0);
  a.schedule(doc("a"));
  await vi.advanceTimersByTimeAsync(500);
  a.schedule(doc("b"));
  await vi.advanceTimersByTimeAsync(749);
  expect(save).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(save).toHaveBeenCalledTimes(1);
  expect(save.mock.calls[0]?.[0].project.title).toBe("b");
  expect(a.revision).toBe(1);
  a.schedule(doc("c"));
  await a.close();
  expect(save).toHaveBeenCalledTimes(2);
  expect(a.dirty).toBe(false);
  expect(() => a.schedule(doc("d"))).toThrow();
});
it("serializes saves while retaining edits arriving in flight", async () => {
  let resolve!: (value: { document: EditorProject; revision: number }) => void;
  const save = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    )
    .mockImplementation(async (document: EditorProject, revision: number) => ({
      document,
      revision: revision + 1,
    }));
  const a = new ProjectAutosave(save, 4);
  a.schedule(doc("a"));
  const flush = a.flush();
  a.schedule(doc("b"));
  expect(save).toHaveBeenCalledTimes(1);
  resolve({ document: doc("a"), revision: 5 });
  await flush;
  expect(save).toHaveBeenCalledTimes(2);
  expect(save.mock.calls[1]?.[1]).toBe(5);
  expect(a.revision).toBe(6);
  expect(a.dirty).toBe(false);
  a.discard();
});
it("retains dirty state on conflict/failure and only retries explicitly", async () => {
  vi.useFakeTimers();
  const failure = new Error("revision conflict");
  const save = vi
    .fn()
    .mockRejectedValueOnce(failure)
    .mockImplementation(async (document: EditorProject, revision: number) => ({
      document,
      revision: revision + 1,
    }));
  const a = new ProjectAutosave(save, 2);
  a.schedule(doc("unsaved"));
  await vi.advanceTimersByTimeAsync(750);
  expect(a.error).toBe(failure);
  expect(a.pending?.project.title).toBe("unsaved");
  expect(a.revision).toBe(2);
  await vi.advanceTimersByTimeAsync(10000);
  expect(save).toHaveBeenCalledTimes(1);
  await a.flush();
  expect(a.dirty).toBe(false);
  expect(a.error).toBeUndefined();
});
it("discard cancels the pending timer; invalid documents never schedule", async () => {
  vi.useFakeTimers();
  const save = vi.fn();
  const a = new ProjectAutosave(save, 0);
  const invalid = doc("bad");
  invalid.project.tracks = [];
  expect(() => a.schedule(invalid)).toThrow();
  a.schedule(doc("discard"));
  a.discard();
  await vi.runAllTimersAsync();
  expect(save).not.toHaveBeenCalled();
  expect(a.dirty).toBe(false);
});

it("discard does not resurrect edits when an in-flight save fails", async () => {
  let reject!: (error: Error) => void;
  const a = new ProjectAutosave(
    () =>
      new Promise((_, fail) => {
        reject = fail;
      }),
    0,
  );
  a.schedule(doc("discard while saving"));
  const saving = a.flush();
  a.discard();
  reject(new Error("offline"));
  await expect(saving).rejects.toThrow("offline");
  expect(a.dirty).toBe(false);
});
