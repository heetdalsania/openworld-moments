// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId } from "react";
import {
  type Motion,
  setAppearance,
  TEXT_SIZES,
  type TextSize,
  type Theme,
  usePreferences,
} from "./preferences";

const THEMES: { id: Theme; label: string }[] = [
  { id: "system", label: "Match my system" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
  { id: "high-contrast", label: "High contrast" },
];

/** M31: theme, text size and motion. System settings (contrast, motion) still apply. */
export function AppearanceSettings({ embedded = false }: { embedded?: boolean }) {
  const { appearance } = usePreferences();
  const id = useId();
  const body = (
    <>
      <div className="row">
        <label>
          Theme{" "}
          <select
            value={appearance.theme}
            onChange={(e) => setAppearance({ theme: e.target.value as Theme })}
          >
            {THEMES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Text size{" "}
          <select
            value={appearance.textSize}
            onChange={(e) => setAppearance({ textSize: Number(e.target.value) as TextSize })}
          >
            {TEXT_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}%
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={appearance.motion === "reduce"}
          onChange={(e) =>
            setAppearance({ motion: (e.target.checked ? "reduce" : "system") as Motion })
          }
        />
        Reduce motion (also follows your system setting)
      </label>
      <p className="muted">
        Windows contrast themes and the system text-size setting are also respected. Status is
        always shown in words, never by color alone.
      </p>
    </>
  );
  if (embedded) return <div className="panel appearance">{body}</div>;
  return (
    <section className="panel appearance" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`}>Display and motion</h2>
      {body}
    </section>
  );
}
