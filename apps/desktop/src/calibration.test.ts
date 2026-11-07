// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import {
  adjust,
  normalized,
  pictureBox,
  pixels,
  point,
  preprocess,
  rect,
  validROI,
  type ROI,
} from "./calibration";
describe("upright normalized regions", () => {
  it.each([
    [1280, 720],
    [1920, 1080],
    [3840, 2160],
    [1440, 1080],
    [1080, 1920],
    [2560, 1080],
  ])("round trips %i × %i", (w, h) => {
    const r: ROI = [0.125, 0.25, 0.625, 0.5];
    expect(normalized(pixels(r, w, h), w, h)).toEqual(r);
    const box = pictureBox(800, 600, w, h);
    expect(point(box.x + r[0] * box.width, box.y + r[1] * box.height, box)).toEqual([r[0], r[1]]);
    expect(point(-100, -100, box)).toEqual([0, 0]);
    expect(point(2000, 2000, box)).toEqual([1, 1]);
  });
  it("moves/resizes one source pixel, clamps at each edge", () => {
    const r: ROI = [0.25, 0.25, 0.5, 0.5];
    expect(adjust(r, 1, -1, 1920, 1080)).toEqual([0.25 + 1 / 1920, 0.25 - 1 / 1080, 0.5, 0.5]);
    expect(adjust(r, 1, 1, 1920, 1080, true)).toEqual([0.25, 0.25, 0.5 + 1 / 1920, 0.5 + 1 / 1080]);
    expect(adjust(r, 9999, 9999, 1920, 1080)).toEqual([0.5, 0.5, 0.5, 0.5]);
    expect(adjust(r, -9999, -9999, 1920, 1080, true)).toEqual([0.25, 0.25, 1 / 1920, 1 / 1080]);
    expect(rect([0.8, 0.9], [0.1, 0.2])).toEqual([0.1, 0.2, 0.7000000000000001, 0.7]);
  });
  it.each([
    [0.9, 0, 0.2, 1],
    [0, 0, 0, 1],
    [NaN, 0, 1, 1],
    [-0.1, 0, 1, 1],
    [0, 0, Infinity, 1],
  ])("rejects invalid %j", (...values) => expect(validROI(values as ROI)).toBe(false));
  it("previews grayscale and threshold without changing source pixels", () => {
    const source = new Uint8ClampedArray([255, 0, 0, 255, 255, 255, 255, 255]);
    const copy = source.slice();
    preprocess(copy, "gray", 200);
    expect([...copy]).toEqual([76, 76, 76, 255, 255, 255, 255, 255]);
    preprocess(copy, "threshold", 200);
    expect([...copy]).toEqual([0, 0, 0, 255, 255, 255, 255, 255]);
    expect(source[0]).toBe(255);
  });
});
