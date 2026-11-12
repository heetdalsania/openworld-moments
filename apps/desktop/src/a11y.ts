// SPDX-License-Identifier: AGPL-3.0-or-later
import { type RefObject, useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/** Focusable elements inside `container`, in document order. */
export function focusables(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) => !el.hasAttribute("hidden") && el.getAttribute("aria-hidden") !== "true",
  );
}

/**
 * M31 modal dialog focus: move focus in on open, keep Tab and Shift+Tab inside, close on
 * Escape, and give focus back to whatever opened the dialog when it closes.
 */
export function useDialogFocus(
  container: RefObject<HTMLElement | null>,
  onClose: () => void,
  initial?: RefObject<HTMLElement | null>,
): void {
  // The latest callback, so an inline arrow does not re-run the effect (and move focus).
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = container.current;
    (initial?.current ?? (root ? focusables(root)[0] : undefined))?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab" || !container.current) return;
      const items = focusables(container.current);
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      const inside = active instanceof Node && container.current.contains(active);
      if (event.shiftKey && (active === first || !inside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !inside)) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (opener?.isConnected) opener.focus();
    };
  }, [container, initial]);
}
