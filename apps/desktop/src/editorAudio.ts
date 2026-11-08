// SPDX-License-Identifier: AGPL-3.0-or-later
import type { AudioSettings } from "@openworld-moments/contracts";
interface Range {
  start_ms: number;
  end_ms: number;
}
export type AudioOperation =
  | { action: "project-gain"; gain_db: number }
  | { action: "mute" | "unmute"; start_ms: number; end_ms: number }
  | { action: "range-gain"; start_ms: number; end_ms: number; gain_db: number }
  | { action: "clear-gain"; start_ms: number; end_ms: number };
function subtract<T extends Range>(items: T[], range: Range): T[] {
  return items.flatMap((item) =>
    item.end_ms <= range.start_ms || item.start_ms >= range.end_ms
      ? [item]
      : [
          ...(item.start_ms < range.start_ms ? [{ ...item, end_ms: range.start_ms }] : []),
          ...(item.end_ms > range.end_ms ? [{ ...item, start_ms: range.end_ms }] : []),
        ],
  );
}
export function editAudio(
  audio: AudioSettings,
  op: AudioOperation,
  duration: number,
): AudioSettings {
  if (!["project-gain", "mute", "unmute", "range-gain", "clear-gain"].includes(op.action))
    throw new Error("Unknown audio operation.");
  const out = structuredClone(audio);
  if (op.action === "project-gain") {
    out.gain_db = op.gain_db;
    return out;
  }
  if (
    !Number.isSafeInteger(op.start_ms) ||
    !Number.isSafeInteger(op.end_ms) ||
    op.start_ms < 0 ||
    op.start_ms >= op.end_ms ||
    op.end_ms > duration
  )
    throw new Error("Choose a nonempty audio range inside the project.");
  if (op.action === "mute") {
    const ranges = [...out.mute_ranges, { start_ms: op.start_ms, end_ms: op.end_ms }].sort(
      (a, b) => a.start_ms - b.start_ms,
    );
    out.mute_ranges = [];
    for (const range of ranges) {
      const last = out.mute_ranges.at(-1);
      if (last && range.start_ms <= last.end_ms) last.end_ms = Math.max(last.end_ms, range.end_ms);
      else out.mute_ranges.push(range);
    }
  } else if (op.action === "unmute") out.mute_ranges = subtract(out.mute_ranges, op);
  else {
    out.gain_ranges = subtract(out.gain_ranges ?? [], op);
    if (op.action === "range-gain")
      out.gain_ranges.push({ start_ms: op.start_ms, end_ms: op.end_ms, gain_db: op.gain_db });
    out.gain_ranges.sort((a, b) => a.start_ms - b.start_ms);
  }
  return out;
}
export function audioAt(
  audio: AudioSettings,
  ms: number,
): { muted: boolean; gainDb: number; linear: number } {
  const muted = audio.mute_ranges.some((r) => r.start_ms <= ms && ms < r.end_ms);
  const gainDb =
    audio.gain_ranges?.find((r) => r.start_ms <= ms && ms < r.end_ms)?.gain_db ?? audio.gain_db;
  return { muted, gainDb, linear: muted ? 0 : 10 ** (gainDb / 20) };
}
/** One graph per pair of mounted video elements; created only by a play gesture. */
export class EditorAudio {
  private context: AudioContext | undefined;
  private gains: GainNode[] = [];
  private elements: HTMLVideoElement[] = [];
  private linear = 1;
  private failure: unknown;
  async start(elements: HTMLVideoElement[]): Promise<void> {
    if (this.failure) throw this.failure;
    this.elements = elements;
    if (typeof AudioContext === "undefined") {
      if (this.linear > 1)
        throw new Error(
          "This preview cannot amplify audio. Choose gain at or below 0 dB; the saved gain remains available to the renderer.",
        );
      this.apply(this.linear);
      return;
    }
    if (!this.context) {
      try {
        this.context = new AudioContext();
        for (const video of elements) {
          const source = this.context.createMediaElementSource(video),
            gain = this.context.createGain();
          source.connect(gain).connect(this.context.destination);
          this.gains.push(gain);
        }
      } catch (error) {
        this.failure = error;
        this.close();
        throw error;
      }
    }
    this.apply(this.linear);
    await this.context.resume();
  }
  apply(linear: number): void {
    this.linear = linear;
    if (this.context)
      for (const gain of this.gains) gain.gain.setValueAtTime(linear, this.context.currentTime);
    else for (const video of this.elements) video.volume = Math.min(1, Math.max(0, linear));
  }
  close(): void {
    void this.context?.close().catch(() => undefined);
  }
}
