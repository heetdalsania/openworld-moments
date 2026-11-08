// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { fetchWaveform, type Waveform } from "./media";
import type { Segment } from "./timeline";

export function SegmentWave({ segment, durationMs }: { segment: Segment; durationMs: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [wave, setWave] = useState<Waveform | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchWaveform(segment.assetId)
      .then((w) => {
        if (!cancelled) setWave(w);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [segment.assetId]);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext?.("2d");
    if (!element || !context || !wave) return;
    const { width, height } = element;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#6b8afd";
    // Only the part of the clip that plays here.
    const from = (segment.sourceInMs / 1000) * wave.bucketsPerSecond;
    const to = Math.min(wave.peaks.length, (segment.sourceOutMs / 1000) * wave.bucketsPerSecond);
    const span = Math.max(1, to - from);
    for (let x = 0; x < width; x++) {
      const a = Math.floor(from + (x / width) * span);
      const b = Math.max(a + 1, Math.floor(from + ((x + 1) / width) * span));
      let peak = 0;
      for (let i = a; i < b && i < wave.peaks.length; i++)
        peak = Math.max(peak, wave.peaks[i] ?? 0);
      const h = Math.max(1, (peak / 255) * height);
      context.fillRect(x, (height - h) / 2, 1, h);
    }
  }, [
    wave,
    segment.sourceInMs,
    segment.sourceOutMs,
    segment.virtualStartMs,
    segment.virtualEndMs,
    durationMs,
  ]);
  if (!wave) return null;
  return (
    <canvas
      ref={canvas}
      className="segment-wave"
      width={Math.max(
        8,
        Math.round(
          (800 * (segment.virtualEndMs - segment.virtualStartMs)) / Math.max(1, durationMs),
        ),
      )}
      height={32}
      aria-hidden="true"
    />
  );
}
