// SPDX-License-Identifier: AGPL-3.0-or-later
// Coordinates always refer to the upright picture, excluding letterbox bars.
export type ROI = [number, number, number, number];
export type Regions = Record<string, ROI>;
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
export function pictureBox(
  width: number,
  height: number,
  frameWidth: number,
  frameHeight: number,
): Box {
  const scale = Math.min(width / frameWidth, height / frameHeight);
  const w = frameWidth * scale,
    h = frameHeight * scale;
  return { x: (width - w) / 2, y: (height - h) / 2, width: w, height: h };
}
export function point(x: number, y: number, box: Box): [number, number] {
  return [clamp((x - box.x) / box.width, 0, 1), clamp((y - box.y) / box.height, 0, 1)];
}
export function pixels(r: ROI, width: number, height: number): ROI {
  return [r[0] * width, r[1] * height, r[2] * width, r[3] * height];
}
export function normalized(r: ROI, width: number, height: number): ROI {
  return [r[0] / width, r[1] / height, r[2] / width, r[3] / height];
}
export function validROI(r: ROI): boolean {
  return (
    r.every(Number.isFinite) &&
    r[0] >= 0 &&
    r[1] >= 0 &&
    r[2] > 0 &&
    r[3] > 0 &&
    r[0] + r[2] <= 1 &&
    r[1] + r[3] <= 1
  );
}
export function rect(a: [number, number], b: [number, number]): ROI {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])];
}
/** One source pixel per arrow; Shift ten pixels; Alt resizes from the bottom right. */
export function adjust(
  r: ROI,
  dx: number,
  dy: number,
  width: number,
  height: number,
  resize = false,
): ROI {
  const [x, y, w, h] = r;
  return resize
    ? [x, y, clamp(w + dx / width, 1 / width, 1 - x), clamp(h + dy / height, 1 / height, 1 - y)]
    : [clamp(x + dx / width, 0, 1 - w), clamp(y + dy / height, 0, 1 - h), w, h];
}
export function regionDiff(base: Regions, current: Regions): Regions {
  return Object.fromEntries(
    Object.entries(current).filter(([name, r]) => JSON.stringify(r) !== JSON.stringify(base[name])),
  );
}
export type Preprocess = "color" | "gray" | "threshold";
/** Local preview only. Does not write source frames, change the profile or emit events. */
export function preprocess(data: Uint8ClampedArray, mode: Preprocess, threshold: number): void {
  if (mode === "color") return;
  for (let i = 0; i < data.length; i += 4) {
    const gray = Math.round(
      0.299 * (data[i] ?? 0) + 0.587 * (data[i + 1] ?? 0) + 0.114 * (data[i + 2] ?? 0),
    );
    const value = mode === "threshold" ? (gray >= threshold ? 255 : 0) : gray;
    data[i] = value;
    data[i + 1] = value;
    data[i + 2] = value;
  }
}
