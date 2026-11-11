# M40 — Windows deferred verification (non-blocking)

## Objective

Run, on real Windows 11 x64 hardware, the checks the maintainer waived while
completing M29 and M10, so that behaviour so far verified only by automated
tests is confirmed on a Windows client. This is a last-resort confirmation
pass. **No milestone depends on M40, and it gates no release.** Defects it finds
become ordinary follow-up issues.

## Dependencies

M29 and M10 merged (both complete). It can run at any time after that,
including after M32 or M39. Run it on the newest available Windows installer.

## Required context

Read `AGENTS.md`, the [M29 handoff](./M29-handoff.md), the
[M29 client report](./M29-windows-client-report.md), the
[Windows packaging guide](../architecture/windows-packaging.md), the
[phone upload guide](../guides/phone-upload.md) and the
[M29 retest prompt](./M29-windows-rerun-prompt.md).

## In scope

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

## Out of scope

- Re-running steps that already passed in the M29 client run, code changes
  (open issues instead), signing, publishing, macOS, and detector or
  transcription quality.

## Implementation steps

1. Use a Windows 11 x64 laptop or PC, a standard account for the
   standard-account item, and a disposable library. Keep the machine clean as the
   M29 runbook requires.
2. Download the newest installer candidate (or published release) and verify its
   checksum.
3. Start every installer from File Explorer and the app from the Start menu. A
   Claude Code session may guide the tester, but must not launch installers or
   the app from its own shell (MSIX container redirection invalidated M29 6.2 and
   6.3).
4. Run each in-scope item and record expected, observed and Pass/Fail.

## Acceptance criteria

- Every in-scope item has a recorded result on physical Windows 11 x64 hardware,
  with OS, WebView2, account type, artifact hash and phone model.
- Any failure has a linked follow-up issue with reproduction steps.

## Required validation

- The in-scope matrix above on a clean Windows 11 x64 client.
- No repository checks are required unless a fix is included; fixes belong in
  their own milestone or follow-up PR.

## Handoff

Add `docs/milestones/M40-windows-deferred-report.md` with the results, update the
M40 ledger row, and link any follow-up issues. Mark M40 complete once every item
has a recorded result, whether or not it passed: its purpose is to replace a
waiver with evidence, not to gate a release.
