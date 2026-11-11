# User guides

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31). See [Validation](#validation).

Task-based guides for people using the app. None of them need a terminal.

## Start here

- [Getting started](./getting-started.md): install, first-run setup, then import,
  review, edit, render and find the video. Includes the keyboard-only path.

## Getting clips into the app

- [Xbox captures through OneDrive](./xbox-onedrive.md)
- [PlayStation and other phone clips](./phone-upload.md)
- [Watched folders](./watched-folders.md): folders that fill up on their own.
- [Capture cards and PC recordings](./capture-card.md)

## Optional features

- [Local transcription](./transcription.md)

## When something goes wrong

- [Troubleshooting](./troubleshooting.md)
- [Diagnostics for support](./diagnostics.md): a report without footage, file names
  or paths.
- [Known limitations](./known-limitations.md)

## Reference

- [Terminology](./terminology.md): the words the app uses.
- [Accessibility](./accessibility.md): keyboard shortcuts, screen readers, display
  settings and the tested-support matrix.
- [Compatibility notes](./compatibility.md): what this version supports.

## Validation

Every guide says which version it applies to and when it was last checked. Screenshots
come from the real interface with synthetic data (`scripts/docs/capture-screenshots.py`),
so they never show real footage or personal paths. An automated test checks that every
link and image in these guides resolves and that each guide carries its version line.

| Guide | How it was checked | Date |
|---|---|---|
| Getting started | Desktop app on macOS (development build) and the screenshot harness; keyboard-only path in automated tests | 2026-11-11 |
| Xbox through OneDrive | Watched-folder flow in automated tests; Xbox and OneDrive steps follow Xbox Support | 2026-11-11 |
| PlayStation and phone clips | Phone transfer opt-in and upload page in automated tests; phone upload on Windows 11 in M29/M10 | 2026-11-11 |
| Watched folders, capture cards | Automated tests and the development build | 2026-11-11 |
| Troubleshooting, diagnostics | Diagnostics redaction tests; each fix matched to the message the app shows | 2026-11-11 |

**Not yet done:** a full pass of every guide on a clean Windows 11 standard-user account.
That run belongs to the Windows qualification in M32 and is listed in the M31 handoff.
Until then, report anything that differs with [diagnostics](./diagnostics.md).
