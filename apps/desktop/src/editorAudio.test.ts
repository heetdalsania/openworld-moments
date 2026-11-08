// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, expect, it, vi } from "vitest";
import { load } from "@openworld-moments/contracts";
import fixture from "../../../packages/contracts/fixtures/editor-project/valid/edited.json";
import { applyCommand, EditorHistory } from "./editor";
import { audioAt, EditorAudio } from "./editorAudio";
afterEach(() => vi.unstubAllGlobals());
it("applies absolute project/range gain, mute precedence, exclusive ends and partial clear", () => {
  const history = new EditorHistory(load("editor-project", fixture));
  history.execute({ kind: "audio", operation: { action: "project-gain", gain_db: 6 } });
  history.execute({
    kind: "audio",
    operation: { action: "range-gain", start_ms: 100, end_ms: 500, gain_db: -6 },
  });
  expect(audioAt(history.document.project.audio, 150).linear).toBeCloseTo(10 ** (-6 / 20));
  history.execute({ kind: "audio", operation: { action: "mute", start_ms: 100, end_ms: 300 } });
  history.execute({ kind: "audio", operation: { action: "mute", start_ms: 200, end_ms: 400 } });
  expect(history.document.project.audio.mute_ranges[0]).toEqual({ start_ms: 100, end_ms: 400 });
  expect(audioAt(history.document.project.audio, 150).linear).toBe(0);
  history.execute({ kind: "audio", operation: { action: "unmute", start_ms: 200, end_ms: 300 } });
  expect(audioAt(history.document.project.audio, 200).muted).toBe(false);
  expect(audioAt(history.document.project.audio, 300).muted).toBe(true);
  const before = history.document;
  history.undo();
  history.redo();
  expect(history.document).toEqual(before);
  history.execute({
    kind: "audio",
    operation: { action: "clear-gain", start_ms: 200, end_ms: 300 },
  });
  expect(audioAt(history.document.project.audio, 200).gainDb).toBe(6);
  expect(audioAt(history.document.project.audio, 199).gainDb).toBe(-6);
  expect(() =>
    applyCommand(history.document, {
      kind: "audio",
      operation: { action: "project-gain", gain_db: 25 },
    }),
  ).toThrow();
  expect(() =>
    applyCommand(history.document, {
      kind: "audio",
      operation: { action: "mute", start_ms: 0, end_ms: 999999 },
    }),
  ).toThrow();
});
it("connects each mounted media element once and applies linear gain including amplification and mute", async () => {
  const values: number[] = [],
    source = vi.fn(() => ({ connect: vi.fn(() => ({ connect: vi.fn() })) })),
    resume = vi.fn(async () => undefined),
    close = vi.fn(async () => undefined);
  class Context {
    currentTime = 1;
    destination = {};
    createMediaElementSource = source;
    createGain = () => ({ gain: { setValueAtTime: (n: number) => values.push(n) } });
    resume = resume;
    close = close;
  }
  vi.stubGlobal("AudioContext", Context);
  const audio = new EditorAudio();
  const elements = [{}, {}] as HTMLVideoElement[];
  await audio.start(elements);
  await audio.start(elements);
  expect(source).toHaveBeenCalledTimes(2);
  audio.apply(2);
  audio.apply(0);
  expect(values.slice(-4)).toEqual([2, 2, 0, 0]);
  audio.close();
  expect(close).toHaveBeenCalledOnce();
});
it("fallback attenuates and mutes but refuses unsupported positive gain", async () => {
  vi.stubGlobal("AudioContext", undefined);
  const audio = new EditorAudio(),
    video = { volume: 1 } as HTMLVideoElement;
  audio.apply(0.5);
  await audio.start([video]);
  expect(video.volume).toBe(0.5);
  audio.apply(0);
  expect(video.volume).toBe(0);
  audio.apply(2);
  await expect(audio.start([video])).rejects.toThrow("cannot amplify");
});
