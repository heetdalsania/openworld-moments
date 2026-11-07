// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { adjust, point, rect, validROI, type Regions, type ROI } from "./calibration";

export function RoiCanvas({
  image,
  width,
  height,
  regions,
  base,
  selected,
  onSelect,
  onChange,
  name,
  compare,
}: {
  image: string;
  width: number;
  height: number;
  regions: Regions;
  base: Regions;
  selected: string;
  onSelect: (name: string) => void;
  onChange: (regions: Regions) => void;
  name: string;
  compare: boolean;
}) {
  const [mode, setMode] = useState<"draw" | "move" | "resize">("move");
  const [draft, setDraft] = useState<ROI | null>(null);
  const drag = useRef<{
    start: [number, number];
    roi: ROI;
    name: string;
    mode: typeof mode;
  } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const position = (e: PointerEvent) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return [0, 0] as [number, number];
    return point(e.clientX - box.left, e.clientY - box.top, {
      x: 0,
      y: 0,
      width: box.width,
      height: box.height,
    });
  };
  function start(e: PointerEvent<SVGSVGElement>) {
    if (e.button !== 0) return;
    const key = mode === "draw" ? name : selected;
    if (!/^[a-z0-9]+(?:[-_][a-z0-9]+)*$/.test(key) || (mode === "draw" && key in regions)) return;
    const r = regions[key];
    if (mode !== "draw" && !r) return;
    svg.current?.focus();
    drag.current = { start: position(e), roi: r ?? [0, 0, 0, 0], name: key, mode };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent<SVGSVGElement>) {
    const d = drag.current;
    if (!d) return;
    const p = position(e),
      dx = (p[0] - d.start[0]) * width,
      dy = (p[1] - d.start[1]) * height;
    setDraft(
      d.mode === "draw"
        ? rect(d.start, p)
        : adjust(d.roi, dx, dy, width, height, d.mode === "resize"),
    );
  }
  function end(e: PointerEvent<SVGSVGElement>) {
    const d = drag.current;
    if (d) {
      const p = position(e);
      const r =
        d.mode === "draw"
          ? rect(d.start, p)
          : adjust(
              d.roi,
              (p[0] - d.start[0]) * width,
              (p[1] - d.start[1]) * height,
              width,
              height,
              d.mode === "resize",
            );
      if (validROI(r)) {
        onChange({ ...regions, [d.name]: r });
        onSelect(d.name);
      }
    }
    drag.current = null;
    setDraft(null);
  }
  function keyboard(e: KeyboardEvent, key: string, r: ROI) {
    const delta: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const vector = delta[e.key];
    if (e.key === "Escape") {
      drag.current = null;
      setDraft(null);
    }
    if (!vector) return;
    e.preventDefault();
    e.stopPropagation();
    onSelect(key);
    const multiplier = e.shiftKey ? 10 : 1;
    onChange({
      ...regions,
      [key]: adjust(r, vector[0] * multiplier, vector[1] * multiplier, width, height, e.altKey),
    });
  }
  return (
    <>
      <label>
        Pointer tool{" "}
        <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
          <option value="move">Move selected region</option>
          <option value="resize">Resize selected region</option>
          <option value="draw">Draw new region</option>
        </select>
      </label>
      <p id="roi-help" className="muted">
        Tab to a region. Arrows move one source pixel; Shift moves ten; Alt + arrows resize. Drag
        with the selected tool. Escape cancels a drag.
      </p>
      <div className="roi-stage" style={{ aspectRatio: `${width}/${height}` }}>
        <img src={image} alt="Selected calibration frame" draggable={false} />
        <svg
          ref={svg}
          tabIndex={-1}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              drag.current = null;
              setDraft(null);
            }
            const r = regions[selected];
            if (r) keyboard(e, selected, r);
          }}
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          aria-label="Region editor"
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={end}
          onPointerCancel={() => {
            drag.current = null;
            setDraft(null);
          }}
        >
          {compare &&
            Object.entries(base).map(([key, r]) => (
              <rect
                key={`base-${key}`}
                x={r[0]}
                y={r[1]}
                width={r[2]}
                height={r[3]}
                className="roi-base"
              />
            ))}
          {Object.entries(regions).map(([key, r]) => (
            <rect
              key={key}
              x={r[0]}
              y={r[1]}
              width={r[2]}
              height={r[3]}
              tabIndex={0}
              role="button"
              aria-label={`Region ${key}`}
              aria-pressed={selected === key}
              aria-describedby="roi-help"
              className={selected === key ? "roi selected" : "roi"}
              onFocus={() => onSelect(key)}
              onPointerDown={(e) => {
                if (mode !== "draw") onSelect(key);
                if (mode !== "draw" && selected !== key) e.stopPropagation();
              }}
              onKeyDown={(e) => keyboard(e, key, r)}
            />
          ))}
          {draft && (
            <rect
              x={draft[0]}
              y={draft[1]}
              width={draft[2]}
              height={draft[3]}
              className="roi-draft"
            />
          )}
        </svg>
      </div>
    </>
  );
}
