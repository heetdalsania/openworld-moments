// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useRef } from "react";
import { useDialogFocus } from "./a11y";
import { isMac, shortcut } from "./keys";

export interface ShortcutGroup {
  title: string;
  rows: { keys: string; action: string }[];
}

/**
 * Every keyboard shortcut, in the platform's notation. macOS adds the menu bar's
 * shortcuts (M38); the in-app shortcuts are the same on both platforms, with ⌘ for Ctrl.
 */
export function shortcutGroups(mac: boolean = isMac()): ShortcutGroup[] {
  const k = (...keys: string[]) => shortcut(keys, mac);
  const groups: ShortcutGroup[] = [
    {
      title: "Everywhere",
      rows: [
        { keys: "Tab, Shift+Tab", action: "Move between controls" },
        { keys: "Enter, Space", action: "Activate a button, link or checkbox" },
        { keys: "First Tab on a page", action: "Skip to content" },
        { keys: `/ or ${k("Mod", "K")}`, action: "Open Search (or focus the search box)" },
        { keys: "Esc", action: "Close a dialog; clear the search box" },
      ],
    },
  ];
  if (mac)
    groups.push({
      title: "Menu bar (macOS)",
      rows: [
        { keys: k("Mod", ","), action: "Settings" },
        { keys: k("Shift", "Mod", "I"), action: "Import" },
        { keys: k("Mod", "N"), action: "New project from a session" },
        { keys: k("Shift", "Mod", "R"), action: "Show library in Finder" },
        { keys: k("Mod", "F"), action: "Find (Search)" },
        {
          keys: `${k("Mod", "1")}, ${k("Mod", "2")}, ${k("Mod", "3")}, ${k("Mod", "4")}`,
          action: "Library, Sessions, Projects, Search",
        },
        { keys: k("Alt", "Mod", "J"), action: "Show background jobs" },
        {
          keys: `${k("Mod", "=")}, ${k("Mod", "-")}, ${k("Mod", "0")}`,
          action: "Bigger text, smaller text, actual size",
        },
        { keys: k("Mod", "/"), action: "Keyboard shortcuts (this list)" },
        { keys: k("Ctrl", "Mod", "F"), action: "Enter or leave full screen" },
        { keys: `${k("Mod", "M")}, ${k("Mod", "H")}`, action: "Minimize, hide the app" },
        {
          keys: k("Mod", "W"),
          action: "Close the window (quits; asks first if work would be lost)",
        },
        {
          keys: k("Mod", "Q"),
          action: "Quit (asks first if jobs are running or edits are unsaved)",
        },
      ],
    });
  groups.push(
    {
      title: "Session player",
      rows: [
        { keys: "Space or K", action: "Play or pause" },
        { keys: "Left, Right", action: "Back or forward 5 seconds" },
        { keys: ", and .", action: "Previous or next frame" },
        { keys: "[ and ]", action: "Previous or next clip boundary" },
        { keys: "Home, End", action: "Start or end" },
        { keys: "R", action: "Show or hide repeated footage" },
        { keys: "M", action: "Mute" },
      ],
    },
    {
      title: "Story editor",
      rows: [
        { keys: "Space or K", action: "Play or pause" },
        { keys: ", and .", action: "Previous or next frame" },
        { keys: "[ and ]", action: "Previous or next cut boundary" },
        { keys: "Home, End", action: "Start or end" },
        { keys: "S", action: "Split the selected cut at the playhead" },
        { keys: "Delete", action: "Remove the selected cut" },
        { keys: `${k("Mod", "Z")}, ${k("Shift", "Mod", "Z")}`, action: "Undo, redo" },
        { keys: k("Mod", "S"), action: "Save now" },
      ],
    },
  );
  return groups;
}

/** M38: Help ▸ Keyboard Shortcuts, also reachable from Settings → Help. */
export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const headingId = useId();
  useDialogFocus(dialog, onClose, close);
  return (
    <div className="overlay">
      <section
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="dialog shortcuts-dialog"
      >
        <h2 id={headingId}>Keyboard shortcuts</h2>
        {shortcutGroups().map((group) => (
          <table key={group.title} className="shortcuts">
            <caption>{group.title}</caption>
            <thead>
              <tr>
                <th scope="col">Keys</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => (
                <tr key={row.action}>
                  <td>
                    <kbd>{row.keys}</kbd>
                  </td>
                  <td>{row.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
        <div className="row">
          <button type="button" ref={close} className="primary" onClick={onClose}>
            Close
          </button>
        </div>
      </section>
    </div>
  );
}
