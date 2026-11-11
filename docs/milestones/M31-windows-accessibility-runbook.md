# M31 Windows accessibility and guide runbook

The manual checks M31 needs on real Windows. Everything else (axe-core, contrast,
keyboard flows, zoom, narrow windows, forced colors, reduced motion, diagnostics
redaction) is automated; see the [M31 handoff](./M31-handoff.md).

Use the newest successful CI candidate from the M31 pull request (Windows job artifact)
and record results in a copy of the table at the end. About 60–90 minutes.

## 0. Machine

- Windows 11 x64 with a **new standard (non-administrator) local account** that has
  never run OpenWorld Moments.
- Narrator (built in) and [NVDA](https://www.nvaccess.org/download/) installed.
- A few short synthetic or self-recorded test videos. Never use leaked, pre-release
  or other people's footage.

## 1. Follow every guide as written

Sign in to the clean account and follow, word for word, each guide in
[docs/guides](../guides/README.md): Getting started (install to **Show in folder**),
Xbox through OneDrive (as far as your accounts allow), PlayStation and phone clips,
Watched folders, Capture cards, Diagnostics, Troubleshooting (spot-check three rows).
Note any step, label or screenshot that does not match what you see.

## 2. Keyboard only

Unplug or ignore the mouse. Starting from a fresh first-run setup:

1. Finish setup with Tab, Space and Enter.
2. Import a video (the file dialog is the standard Windows dialog).
3. Open the clip, open its session, confirm or reject an event.
4. Make a story from a range, trim a cut, move it, render it.
5. Choose **Show in folder** and check File Explorer selects the video.

Check that the focus ring is visible at every step.

## 3. Screen readers

With **Narrator** (Ctrl+Win+Enter), then with **NVDA**:

1. First-run setup: each step's heading is read when it appears; checkbox
   explanations are read with the checkbox.
2. Start an import: when it finishes, *Import finished.* is announced without moving
   focus. Cause a failure (import a renamed text file): the failure is announced.
3. Settings → Diagnostics: preview and save; the preview region is reachable.
4. Import dialog: opening reads its title; Esc returns to **Import**.

## 4. Display settings

1. **Windows contrast theme** (Settings → Accessibility → Contrast themes → *Night
   sky*): controls keep outlines, focus is visible, status text is readable.
2. **Text size 200%** (Settings → Accessibility → Text size) and **Display scale
   200%**: nothing is cut off; no sideways scrolling on Library, Settings, setup.
3. **Animation effects off:** no animated transitions.
4. In the app: Theme *High contrast*, Text size 200%, Reduce motion.

## 5. Diagnostics redaction

Save a diagnostics report with and without **Include error messages** after a failed
import of a file whose name contains your real name. Open the file in Notepad and
confirm it has no file names, paths, user name or tokens.

## Results

| Check | Narrator | NVDA | Result / notes |
|---|---|---|---|
| 1. Guides followed on a clean standard account | — | — | |
| 2. Keyboard-only workflow, focus visible | — | — | |
| 3.1 Setup headings and explanations read | | | |
| 3.2 Completion and failure announced | | | |
| 3.3 Diagnostics preview reachable | | | |
| 3.4 Dialog title, Esc returns focus | | | |
| 4.1 Windows contrast theme | — | — | |
| 4.2 200% text and 200% scale | — | — | |
| 4.3 Animation effects off | — | — | |
| 4.4 In-app display settings | — | — | |
| 5. Diagnostics contain nothing personal | — | — | |
