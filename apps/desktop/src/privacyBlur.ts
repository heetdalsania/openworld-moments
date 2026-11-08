// SPDX-License-Identifier: AGPL-3.0-or-later
import type { BlurOverlay, CropKeyframe } from "@openworld-moments/contracts";
export function blurRegionAt(blur: BlurOverlay, atMs: number): [number, number, number, number] {
  const keys = blur.keyframes ?? [{ at_ms: 0, region: blur.region }];
  const local = Math.max(0, atMs - blur.start_ms);
  for (let i = 1; i < keys.length; i++) {
    const left = keys[i - 1],
      right = keys[i];
    if (left && right && local <= right.at_ms) {
      const f = Math.max(0, Math.min(1, (local - left.at_ms) / (right.at_ms - left.at_ms)));
      return left.region.map((v, n) => v + ((right.region[n] ?? v) - v) * f) as [
        number,
        number,
        number,
        number,
      ];
    }
  }
  return [...(keys.at(-1)?.region ?? blur.region)];
}
export function blurPixels(
  region: number[],
  width: number,
  height: number,
): [number, number, number, number] {
  const [x = 0, y = 0, w = 1, h = 1] = region;
  const pw = Math.min(width, Math.max(8, Math.floor((w * width) / 2 + 0.5) * 2));
  const ph = Math.min(height, Math.max(8, Math.floor((h * height) / 2 + 0.5) * 2));
  return [
    Math.min(width - pw, Math.floor((x * width) / 2 + 1e-9) * 2),
    Math.min(height - ph, Math.floor((y * height) / 2 + 1e-9) * 2),
    pw,
    ph,
  ];
}
/** Clip/rebase linear motion when timeline commands trim, split or reorder a blur. */
export function retimeBlur(
  blur: BlurOverlay,
  oldStart: number,
  oldEnd: number,
  shift: number,
): BlurOverlay {
  const start_ms = Math.max(blur.start_ms, oldStart),
    end_ms = Math.min(blur.end_ms, oldEnd);
  if (!blur.keyframes) return { ...blur, start_ms: start_ms + shift, end_ms: end_ms + shift };
  const keyframes: CropKeyframe[] = [
    { at_ms: 0, region: blurRegionAt(blur, start_ms) },
    ...blur.keyframes
      .filter((k) => k.at_ms + blur.start_ms > start_ms && k.at_ms + blur.start_ms < end_ms)
      .map((k) => ({ ...k, at_ms: k.at_ms + blur.start_ms - start_ms })),
  ];
  const terminal = end_ms - start_ms - 1;
  if (
    terminal > 0 &&
    keyframes.at(-1)?.at_ms !== terminal &&
    blur.keyframes.some((k) => k.at_ms + blur.start_ms > end_ms - 1)
  )
    keyframes.push({ at_ms: terminal, region: blurRegionAt(blur, end_ms - 1) });
  return {
    ...blur,
    start_ms: start_ms + shift,
    end_ms: end_ms + shift,
    region: keyframes[0]?.region ?? blur.region,
    keyframes,
  };
}
/** Same chroma-aligned geometry as FFmpeg. Canvas blur appearance is approximate. */
export function drawPrivacyBlurs(
  ctx: CanvasRenderingContext2D,
  blurs: BlurOverlay[],
  atMs: number,
): void {
  for (const blur of blurs) {
    if (atMs < blur.start_ms || atMs >= blur.end_ms) continue;
    const [x, y, w, h] = blurPixels(blurRegionAt(blur, atMs), ctx.canvas.width, ctx.canvas.height);
    const patch = document.createElement("canvas");
    patch.width = w;
    patch.height = h;
    const p = patch.getContext("2d");
    if (!p) continue;
    p.drawImage(ctx.canvas, x, y, w, h, 0, 0, w, h);
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.filter = `blur(${Math.max(1, Math.min(w, h) / 4)}px)`;
    // Extend patch edges under the clip, avoiding a transparent privacy fringe.
    ctx.drawImage(patch, x - 4, y - 4, w + 8, h + 8);
    ctx.restore();
  }
}
