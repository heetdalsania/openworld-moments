// SPDX-License-Identifier: AGPL-3.0-or-later
// Media URLs served by the host's `owm-media` protocol, by asset ID only: the web view
// never names a filesystem path. Plus the compact waveform format (M08).
export type MediaVariant = "original" | "proxy" | "waveform";

function base(): string {
  // WebView2 (Windows) reaches custom protocols as http://<scheme>.localhost.
  const windows = typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent);
  return windows ? "http://owm-media.localhost" : "owm-media://localhost";
}

export function mediaUrl(assetId: string, variant: MediaVariant): string {
  return `${base()}/asset/${encodeURIComponent(assetId)}/${variant}`;
}

export function thumbnailUrl(assetId: string, index = 1): string {
  return `${base()}/asset/${encodeURIComponent(assetId)}/thumbnail/${index}`;
}

export interface Waveform {
  bucketsPerSecond: number;
  peaks: Uint8Array;
}

/** Parse `owm-waveform` v1: 16-byte header then (peak, rms) byte pairs. */
export function parseWaveform(buffer: ArrayBuffer): Waveform | null {
  if (buffer.byteLength < 16) return null;
  const view = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
  const version = view.getUint16(4, true);
  const rate = view.getUint16(6, true);
  const count = view.getUint32(12, true);
  if (magic !== "OWMW" || version !== 1 || buffer.byteLength !== 16 + 2 * count || rate < 1) {
    return null;
  }
  const pairs = new Uint8Array(buffer, 16);
  const peaks = new Uint8Array(count);
  for (let i = 0; i < count; i++) peaks[i] = pairs[2 * i] ?? 0;
  return { bucketsPerSecond: rate, peaks };
}

export async function fetchWaveform(assetId: string): Promise<Waveform | null> {
  const response = await fetch(mediaUrl(assetId, "waveform"));
  if (!response.ok) return null;
  return parseWaveform(await response.arrayBuffer());
}

export function formatDuration(ms: number): string {
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}
