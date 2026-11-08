// SPDX-License-Identifier: AGPL-3.0-or-later
/** M25 geometry v1. Mirrors render/layout.py. All regions use upright originals. */
import type { Profile, Segment, VerticalCrop } from "@openworld-moments/contracts";
export type Region = [number, number, number, number];
export const FIT: VerticalCrop = {
  layout_version: 1,
  strategy: "fit",
  background: "solid",
  keyframes: [],
};
export function regionAt(layout: VerticalCrop, ms: number): Region {
  const keys = layout.keyframes;
  if (!keys.length || layout.strategy === "fit") return [0, 0, 1, 1];
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1],
      b = keys[i];
    if (!a || !b) continue;
    if (ms < b.at_ms) {
      let q = Math.max(0, Math.min(1, (ms - a.at_ms) / (b.at_ms - a.at_ms)));
      q = q * q * (3 - 2 * q);
      return a.region.map((v, j) => v + ((b.region[j] ?? v) - v) * q) as Region;
    }
  }
  const last = keys.at(-1);
  return last ? ([...last.region] as Region) : [0, 0, 1, 1];
}
export function pixels(r: Region, w: number, h: number): Region {
  if (r.every((n, i) => n === [0, 0, 1, 1][i])) return [0, 0, w, h];
  const cw = Math.min(w, Math.max(2, Math.floor((r[2] * w) / 2 + 1e-9) * 2));
  const ch = Math.min(h, Math.max(2, Math.floor((r[3] * h) / 2 + 1e-9) * 2));
  return [
    Math.min(w - cw, Math.max(0, Math.floor(r[0] * w + 1e-9))),
    Math.min(h - ch, Math.max(0, Math.floor(r[1] * h + 1e-9))),
    cw,
    ch,
  ];
}
export function fitRect(w: number, h: number, ow = 1080, oh = 1920): Region {
  const scale = Math.min(ow / w, oh / h),
    fw = Math.max(2, Math.floor((w * scale) / 2 + 1e-9) * 2),
    fh = Math.max(2, Math.floor((h * scale) / 2 + 1e-9) * 2);
  return [Math.floor((ow - fw) / 2), Math.floor((oh - fh) / 2), fw, fh];
}
export function visibleFraction(r: Region, z: Region): number {
  return (
    (Math.max(0, Math.min(r[0] + r[2], z[0] + z[2]) - Math.max(r[0], z[0])) *
      Math.max(0, Math.min(r[1] + r[3], z[1] + z[3]) - Math.max(r[1], z[1]))) /
    (z[2] * z[3])
  );
}
export function compatibleProfile(
  profile: Profile | undefined,
  w: number,
  h: number,
): Profile | undefined {
  return profile &&
    w >= profile.frame.min_width &&
    h >= profile.frame.min_height &&
    profile.frame.aspect_ratios.some((r) => {
      const [a = 1, b = 1] = r.split(":").map(Number);
      return Math.abs(w / h - a / b) / (a / b) <= 0.01;
    })
    ? profile
    : undefined;
}
export function layoutWarnings(
  layout: VerticalCrop,
  w: number,
  h: number,
  profile?: Profile,
  overlays: { region: Region; keyframes?: { region: Region }[] }[] = [],
): string[] {
  if (!profile) return ["No compatible current profile: protected HUD regions are unknown."];
  const names = profile.safe_zones?.preserve ?? [];
  if (!names.length) return ["The profile declares no protected HUD regions."];
  const times = layout.keyframes.map((k) => k.at_ms);
  if (!times.length) times.push(0);
  times.push(...times.slice(1).map((t, i) => (t + (times[i] ?? 0)) / 2));
  const result: string[] = [];
  for (const name of names) {
    const zone = profile.regions[name];
    if (!zone) {
      result.push(`Protected region ${name}: region unavailable.`);
      continue;
    }
    const boxes: Region[] = [];
    let removed = false;
    for (const t of times) {
      const [x, y, cw, ch] = pixels(regionAt(layout, t), w, h);
      if (visibleFraction([x / w, y / h, cw / w, ch / h], zone) < 0.95 - 1e-9) {
        result.push(`Protected region ${name}: more than 5% is removed by the crop.`);
        removed = true;
        break;
      }
      const [ox, oy, fw, fh] = fitRect(cw, ch);
      const mapped: Region = [
        (ox + ((zone[0] * w - x) * fw) / cw) / 1080,
        (oy + ((zone[1] * h - y) * fh) / ch) / 1920,
        (zone[2] * w * fw) / cw / 1080,
        (zone[3] * h * fh) / ch / 1920,
      ];
      boxes.push(mapped);
    }
    if (!removed && boxes.length) {
      const x = Math.min(...boxes.map((r) => r[0])),
        y = Math.min(...boxes.map((r) => r[1]));
      const right = Math.max(...boxes.map((r) => r[0] + r[2])),
        bottom = Math.max(...boxes.map((r) => r[1] + r[3]));
      const swept: Region = [x, y, right - x, bottom - y],
        area = Math.min(...boxes.map((r) => r[2] * r[3]));
      if (
        overlays.some((o) => {
          const regions = [o.region, ...(o.keyframes ?? []).map((k) => k.region)];
          const x = Math.min(...regions.map((r) => r[0])),
            y = Math.min(...regions.map((r) => r[1]));
          const envelope: Region = [
            x,
            y,
            Math.max(...regions.map((r) => r[0] + r[2])) - x,
            Math.max(...regions.map((r) => r[1] + r[3])) - y,
          ];
          return (visibleFraction(envelope, swept) * swept[2] * swept[3]) / area > 0.05;
        })
      )
        result.push(`Protected region ${name}: a privacy blur may obscure it.`);
    }
  }
  return result;
}
/** One stable decision per cut. No noisy frame-following; no inferred subject. */
export function suggest(
  w: number,
  h: number,
  profile?: Profile,
): { layout: VerticalCrop; confidence: number; reason: string; version: string } {
  const fallback = (reason: string) => ({
    layout: structuredClone(FIT),
    confidence: 0.25,
    reason,
    version: "static-profile/1",
  });
  if (!profile) return fallback("Missing or incompatible profile: keep the complete frame.");
  const names = [
    ...new Set([...(profile.safe_zones?.preserve ?? []), ...(profile.subject_hints ?? [])]),
  ];
  if (!names.length)
    return fallback("No protected regions or subject hints: keep the complete frame.");
  const zones = names.map((n) => (profile.regions[n] ?? [0, 0, 1, 1]) as Region);
  const x = Math.min(...zones.map((r) => r[0])),
    y = Math.min(...zones.map((r) => r[1]));
  const right = Math.max(...zones.map((r) => r[0] + r[2])),
    bottom = Math.max(...zones.map((r) => r[1] + r[3]));
  const ratio = 9 / 16 / (w / h);
  // Largest full-height/width 9:16 window. Fit if the union cannot be preserved.
  const cw = Math.min(1, ratio),
    ch = Math.min(1, 1 / ratio);
  if (right - x > cw || bottom - y > ch)
    return fallback(
      "Conflicting HUD/subject regions cannot fit in a vertical crop: keep the complete frame.",
    );
  const cx = Math.max(0, Math.min(1 - cw, (x + right - cw) / 2)),
    cy = Math.max(0, Math.min(1 - ch, (y + bottom - ch) / 2));
  const layout: VerticalCrop = {
    ...FIT,
    strategy: "fixed",
    keyframes: [{ at_ms: 0, region: [cx, cy, cw, ch] }],
  };
  if (layoutWarnings(layout, w, h, profile).length)
    return fallback("Pixel rounding would remove protected regions: keep the complete frame.");
  return {
    layout,
    confidence: 0.65,
    reason: `Static profile regions: ${names.join(", ")}. No motion or object tracking.`.slice(
      0,
      1000,
    ),
    version: "static-profile/1",
  };
}
/** Keep vertical keys attached to source content after trimming and splitting. */
export function trimVertical(s: Segment, from: number, to: number): VerticalCrop | undefined {
  const v = s.vertical_crop;
  if (!v || v.strategy === "fit") return v && structuredClone(v);
  const offset = from - s.source_in_ms,
    end = to - s.source_in_ms;
  const first = { at_ms: 0, region: regionAt(v, offset) };
  // Trimming reanchors easing at the retained start/end; source coordinates stay intact.
  const keys = v.keyframes
    .filter((k) => k.at_ms > offset && k.at_ms < end)
    .map((k) => ({ ...k, at_ms: k.at_ms - offset }));
  const last = end - offset - 1;
  if (v.strategy === "keyed" && last > 0 && (keys.at(-1)?.at_ms ?? 0) < last)
    keys.push({ at_ms: last, region: regionAt(v, end - 1) });
  return { ...structuredClone(v), keyframes: [first, ...keys] };
}
