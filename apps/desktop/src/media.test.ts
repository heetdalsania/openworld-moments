// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDuration, mediaUrl, parseWaveform, thumbnailUrl } from "./media";
import { parseRoute, routeHref } from "./route";

function waveform(peaks: number[], magic = "OWMW"): ArrayBuffer {
  const buffer = new ArrayBuffer(16 + peaks.length * 2);
  const view = new DataView(buffer);
  [...magic].forEach((c, i) => view.setUint8(i, c.charCodeAt(0)));
  view.setUint16(4, 1, true);
  view.setUint16(6, 50, true);
  view.setUint32(8, 8000, true);
  view.setUint32(12, peaks.length, true);
  peaks.forEach((p, i) => {
    view.setUint8(16 + 2 * i, p);
    view.setUint8(17 + 2 * i, Math.round(p * 0.7));
  });
  return buffer;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("media helpers", () => {
  it("parses the owm-waveform format and rejects anything else", () => {
    const parsed = parseWaveform(waveform([0, 128, 255]));
    expect(parsed?.bucketsPerSecond).toBe(50);
    expect([...(parsed?.peaks ?? [])]).toEqual([0, 128, 255]);
    expect(parseWaveform(waveform([1], "XXXX"))).toBeNull();
    expect(parseWaveform(waveform([1, 2]).slice(0, 17))).toBeNull();
    expect(parseWaveform(new ArrayBuffer(4))).toBeNull();
  });

  it("builds media URLs from asset IDs only", () => {
    const id = "ast_01JCBQ00000000000000000001";
    expect(mediaUrl(id, "proxy")).toBe(`owm-media://localhost/asset/${id}/proxy`);
    expect(thumbnailUrl(id, 3)).toBe(`owm-media://localhost/asset/${id}/thumbnail/3`);
    vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (Windows NT 10.0) Edg/130" });
    expect(mediaUrl(id, "original")).toBe(`http://owm-media.localhost/asset/${id}/original`);
  });

  it("formats durations", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(61_500)).toBe("1:02");
    expect(formatDuration(3_725_000)).toBe("1:02:05");
  });

  it("parses routes and rejects malformed asset IDs", () => {
    const id = "ast_01JCBQ00000000000000000001";
    expect(parseRoute(`#/asset/${id}`)).toEqual({ view: "asset", id });
    expect(parseRoute("#/asset/../../etc")).toEqual({ view: "library" });
    expect(parseRoute("#/settings")).toEqual({ view: "settings" });
    expect(parseRoute("")).toEqual({ view: "library" });
    expect(routeHref({ view: "asset", id })).toBe(`#/asset/${id}`);
  });
});
