// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState, type RefObject } from "react";
import type { Segment, BlurOverlay } from "@openworld-moments/contracts";
import { drawPrivacyBlurs } from "./privacyBlur";
import { FIT, fitRect, pixels, regionAt } from "./verticalLayout";
/** A real 1080×1920 backing surface, driven by the existing two-element player.
 * Native decoders apply rotation; crop coordinates are quantized against originals,
 * then scaled to the decoded proxy. No new decoder or independent audio clock. */
export function VerticalPreview({
  video,
  aspectRatio = "9:16",
  blurs = [],
  cut,
  width,
  height,
  atMs,
  playing,
}: {
  video: RefObject<HTMLVideoElement | null>;
  aspectRatio?: "16:9" | "9:16" | "1:1";
  blurs?: BlurOverlay[];
  cut?: Segment;
  width: number;
  height: number;
  atMs: number;
  playing: boolean;
}) {
  const outputWidth = aspectRatio === "9:16" ? 1080 : 1920;
  const outputHeight = aspectRatio === "16:9" ? 1080 : 1920;
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
          let r = regionAt(layout, ms);
          if (aspectRatio !== "9:16") {
            r = [0, 0, 1, 1];
            const keys = cut?.crop.keyframes ?? [];
            const active = keys.filter((k) => k.at_ms <= ms).at(-1);
            if (active) r = active.region;
            else if (cut?.crop.mode === "fill") {
              const ratio = outputWidth / outputHeight;
              if (width / height > ratio)
                r = [(1 - (height * ratio) / width) / 2, 0, (height * ratio) / width, 1];
              else r = [0, (1 - width / ratio / height) / 2, 1, width / ratio / height];
            }
          }
          const [x, y, w, h] = pixels(r, width, height);
          const [ox, oy, fw, fh] = fitRect(w, h, outputWidth, outputHeight);
          const sx = (x * v.videoWidth) / width,
            sy = (y * v.videoHeight) / height,
            sw = (w * v.videoWidth) / width,
            sh = (h * v.videoHeight) / height;
          ctx.clearRect(0, 0, outputWidth, outputHeight);
          ctx.fillStyle = "black";
          ctx.fillRect(0, 0, outputWidth, outputHeight);
          if (aspectRatio === "9:16" && layout.background === "blur") {
            const scale = Math.max(outputWidth / w, outputHeight / h),
              bw = w * scale,
              bh = h * scale;
            ctx.save();
            ctx.filter = "blur(20px)";
            ctx.drawImage(
              v,
              sx,
              sy,
              sw,
              sh,
              (outputWidth - bw) / 2,
              (outputHeight - bh) / 2,
              bw,
              bh,
            );
            ctx.restore();
          }
          ctx.drawImage(v, sx, sy, sw, sh, ox, oy, fw, fh);
          const timelineMs =
            playing && cut ? cut.timeline_start_ms + v.currentTime * 1000 - cut.source_in_ms : atMs;
          drawPrivacyBlurs(ctx, blurs, timelineMs);
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
  }, [video, cut, width, height, atMs, playing, aspectRatio, blurs, outputWidth, outputHeight]);
  return (
    <>
      <canvas
        ref={canvas}
        className="vertical-preview"
        width={outputWidth}
        height={outputHeight}
        aria-label={
          aspectRatio === "9:16" ? "Vertical preview 1080 by 1920" : "Privacy blur preview"
        }
      />
      {error && <p role="alert">{error}</p>}
    </>
  );
}
