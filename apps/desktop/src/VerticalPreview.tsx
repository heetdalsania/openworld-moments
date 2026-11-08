// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState, type RefObject } from "react";
import type { Segment } from "@openworld-moments/contracts";
import { FIT, fitRect, pixels, regionAt } from "./verticalLayout";
/** A real 1080×1920 backing surface, driven by the existing two-element player.
 * Native decoders apply rotation; crop coordinates are quantized against originals,
 * then scaled to the decoded proxy. No new decoder or independent audio clock. */
export function VerticalPreview({
  video,
  cut,
  width,
  height,
  atMs,
  playing,
}: {
  video: RefObject<HTMLVideoElement | null>;
  cut?: Segment;
  width: number;
  height: number;
  atMs: number;
  playing: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null),
    [error, setError] = useState("");
  useEffect(() => {
    const v = video.current,
      c = canvas.current,
      ctx = c?.getContext("2d");
    if (!v || !c || !ctx) return;
    let frame = 0,
      alive = true;
    const draw = () => {
      if (!alive) return;
      if (v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0) {
        try {
          const layout = cut?.vertical_crop ?? FIT;
          const ms =
            playing && cut
              ? v.currentTime * 1000 - cut.source_in_ms
              : atMs - (cut?.timeline_start_ms ?? 0);
          const [x, y, w, h] = pixels(regionAt(layout, ms), width, height),
            [ox, oy, fw, fh] = fitRect(w, h);
          const sx = (x * v.videoWidth) / width,
            sy = (y * v.videoHeight) / height,
            sw = (w * v.videoWidth) / width,
            sh = (h * v.videoHeight) / height;
          ctx.clearRect(0, 0, 1080, 1920);
          ctx.fillStyle = "black";
          ctx.fillRect(0, 0, 1080, 1920);
          if (layout.background === "blur") {
            const scale = Math.max(1080 / w, 1920 / h),
              bw = w * scale,
              bh = h * scale;
            ctx.save();
            ctx.filter = "blur(20px)";
            ctx.drawImage(v, sx, sy, sw, sh, (1080 - bw) / 2, (1920 - bh) / 2, bw, bh);
            ctx.restore();
          }
          ctx.drawImage(v, sx, sy, sw, sh, ox, oy, fw, fh);
        } catch {
          setError("Vertical preview could not draw this source. Your layout is kept.");
        }
      }
    };
    const loop = () => {
      draw();
      if (playing) frame = requestAnimationFrame(loop);
    };
    loop();
    v.addEventListener("seeked", draw);
    v.addEventListener("loadeddata", draw);
    v.addEventListener("timeupdate", draw);
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      v.removeEventListener("seeked", draw);
      v.removeEventListener("loadeddata", draw);
      v.removeEventListener("timeupdate", draw);
    };
  }, [video, cut, width, height, atMs, playing]);
  return (
    <>
      <canvas
        ref={canvas}
        className="vertical-preview"
        width={1080}
        height={1920}
        aria-label="Vertical preview 1080 by 1920"
      />
      {error && <p role="alert">{error}</p>}
    </>
  );
}
