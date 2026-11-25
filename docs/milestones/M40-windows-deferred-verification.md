# M40 — Deferred device verification (non-blocking)

## Objective

Run, on real hardware, the checks the maintainer waived while completing M10,
M29, M31, M32 and M33–M36, so that behaviour verified so far only by automated tests,
CI runners or synthetic fixtures is confirmed on physical Windows and macOS
machines. This is a last-resort confirmation
pass. **No milestone depends on M40, and it gates no release.** Defects it finds
become ordinary follow-up issues.

## Dependencies

M10, M29, M31 and M33–M36 merged (all complete by maintainer decision). It can
run at any time after that, including after M32 or M39, on the newest available
Windows installer and macOS bundles. Sections are independent; run whichever
hardware is available. Section E needs the M32 release to be published first.

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

### E. Windows public alpha (M32)

M32 prepared the `0.1.0-alpha.32` public alpha without a Windows machine; its
clean-machine checks were waived by maintainer decision
([qualification report](./M32-windows-qualification-report.md)). On a clean
Windows 11 x64 PC, standard account where possible, using the installer
**downloaded with a browser from the published GitHub release**:

- **Download and verify:** the installer's SHA-256 equals its line in the
  release's `checksums.txt`; `gh attestation verify` passes; record the
  SmartScreen prompts (this covers the section A SmartScreen item).
- **Version report:** the footer and **Settings → System check** show
  `0.1.0-alpha.32`, "Packaged runtime" and passing core checks; a saved
  diagnostics report names the same version.
- **End-to-end journey:** import at least two overlapping synthetic or
  self-recorded clips, group them into a session, review (approve, reject or
  add) at least one event on the session timeline, create and trim a project,
  complete the privacy review, then render **both** `horizontal-1080p30` and
  `vertical-1080x1920-30`; both files play and the sources are unchanged.
- **Upgrade from 0.1.0-alpha.29** (if that candidate is still available):
  library, project, render and models retained; schema version stays 19.
- **Console-transfer guides:** follow the [Xbox through OneDrive](../guides/xbox-onedrive.md)
  and [PlayStation and phone clips](../guides/phone-upload.md) guides with the
  current console and companion apps, and record any step that differs.

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
