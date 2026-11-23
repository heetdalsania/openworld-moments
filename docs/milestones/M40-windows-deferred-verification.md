# M40 — Deferred device verification (non-blocking)

## Objective

Run, on real hardware, the checks the maintainer waived while completing M10,
M29, M31 and M33–M36, so that behaviour verified so far only by automated tests,
CI runners or synthetic fixtures is confirmed on physical Windows and macOS
machines. This is a last-resort confirmation
pass. **No milestone depends on M40, and it gates no release.** Defects it finds
become ordinary follow-up issues.

## Dependencies

M10, M29, M31 and M33–M36 merged (all complete by maintainer decision). It can
run at any time after that, including after M32 or M39, on the newest available
Windows installer and macOS bundles. Sections are independent; run whichever
hardware is available.

## Required context

Read `AGENTS.md`, the [M29 handoff](./M29-handoff.md), the
[M29 client report](./M29-windows-client-report.md), the
[Windows packaging guide](../architecture/windows-packaging.md), the
[phone upload guide](../guides/phone-upload.md) and the
[M29 retest prompt](./M29-windows-rerun-prompt.md).

## In scope

### A. Windows 11 x64 (M10, M29)

Each item was waived or only partly covered in the M29 client run:

- **Phone upload, several videos in one session (M10, fixed in #38):** at least
  three phone videos, including one of 2 MB or more, sent one after another,
  where later ones start after earlier ones finish importing. None may be refused
  as "out of space". Re-sending shows "Already in the library".
- **Phone upload refusal of a non-video file (M10 8.3):** not exercised in the
  M29 run because the iOS picker hid non-video files. Use another phone, the
  Files picker, or a renamed file.
- **Single-click model-download cancel (M29 5.4, fixed in #37):** one Cancel in
  Settings moves the job to cancelled. Background jobs says the partial is kept,
  and Resume completes the download.
- **Repair and upgrade outside the Claude app container (M29 6.2, 6.3):** both
  installers are started from File Explorer and the app from the Start menu.
  Library, project, export and active model are retained, and the version is
  correct.
- **Standard (non-administrator) account (M29 ran as administrator with UAC):**
  installs with no elevation prompt, then first launch and import/render. Record
  what happens at the M10 Windows Firewall prompt when the user cannot approve it.
- **SmartScreen on a browser download:** download the installer through a
  browser so it carries Mark-of-the-Web, and record the unsigned-publisher
  prompts.

### B. Windows accessibility (M31)

- Every step of the [M31 Windows accessibility runbook](./M31-windows-accessibility-runbook.md):
  a clean standard-account pass through every user guide, keyboard-only use,
  Narrator and NVDA smoke tests, display settings, and diagnostics redaction.

### C. Intel Mac (M33, M34, M36)

- Physical launch smoke test on an Intel Mac
  ([shell guide](../platforms/macos-development-shell.md#physical-launch-smoke-test)),
  including the bundled worker and media tools and the system check showing
  `x86_64` (M33, M34).
- The [packaged-tool media matrix](../platforms/macos-media-parity.md#test-the-packaged-tools)
  on Intel hardware: VideoToolbox availability, its bitrate mapping, and CPU
  fallback (M36).

### D. Physical Mac files, lifecycle and playback (M35, M36)

- All nine steps of [M35 physical Mac validation](./M35-macos-validation.md):
  external drive, revoked folder access, OneDrive/File Provider cloud-only files,
  sleep/wake, quit and kill recovery, a clean-account phone transfer with
  local-network and firewall prompts, moving the library, and native Save panels.
- The M36 packaged-app player walkthrough: play and seek the synthetic H.264,
  silent, VFR, rotated, HEVC and PQ proxy samples through the app's media
  protocol on Apple Silicon (and Intel if available). Include an extended
  export with thermal observation.

## Out of scope

- Re-running steps that already passed in the M29 client run, code changes
  (open issues instead), signing, notarization, publishing, and detector or
  transcription quality.

## Implementation steps

1. Use a Windows 11 x64 PC (sections A and B) and/or an Intel and an Apple
   Silicon Mac (sections C and D), standard accounts where an item asks for one,
   and disposable libraries. Keep each machine clean as the M29 and M35 runbooks
   require.
2. Download the newest installer candidate (or published release) and verify its
   checksum.
3. Start every installer from File Explorer and the app from the Start menu. A
   Claude Code session may guide the tester, but must not launch installers or
   the app from its own shell (MSIX container redirection invalidated M29 6.2 and
   6.3).
4. Run each in-scope item and record expected, observed and Pass/Fail.

## Acceptance criteria

- Every in-scope item has a recorded result on the physical hardware its section
  names, with OS, architecture, WebView/WebKit version, account type, artifact
  hash and phone model. Items for hardware that is not available stay Pending,
  with the reason recorded.
- Any failure has a linked follow-up issue with reproduction steps.

## Required validation

- The in-scope matrix above on the named physical hardware.
- No repository checks are required unless a fix is included; fixes belong in
  their own milestone or follow-up PR.

## Handoff

Add `docs/milestones/M40-windows-deferred-report.md` with the results, update the
M40 ledger row, and link any follow-up issues. Mark M40 complete once every item
has a recorded result, whether or not it passed: its purpose is to replace a
waiver with evidence, not to gate a release.
