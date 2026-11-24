# OpenWorld Moments 0.1.0-alpha.32 — Windows public alpha

> **Unofficial community project.** OpenWorld Moments is not affiliated with or endorsed by
> Rockstar Games, Take-Two Interactive, Microsoft or Sony. It never connects to a console,
> reads game memory, inspects network traffic or modifies a game. It only processes video
> files you choose.

This is the first public **alpha** of OpenWorld Moments for **Windows 11 x64**. It is an
early, unsigned test build for people comfortable reporting problems. It is not v1.0,
and it does not promise compatibility with any particular game.

- Tag: `v0.1.0-alpha.32` · Installer: `OpenWorld-Moments_0.1.0-alpha.32_Windows_x64-setup.exe`
- Qualification: [Windows qualification report](https://github.com/heetdalsania/openworld-moments/blob/main/docs/milestones/M32-windows-qualification-report.md)
- Everything in this release: [release documents](https://github.com/heetdalsania/openworld-moments/tree/main/docs/releases/0.1.0-alpha.32)

## Before you install: the installer is not signed

The installer has **no Authenticode signature**. When you download it with a browser,
Windows SmartScreen will probably show **"Windows protected your PC"** with an *Unknown
publisher*. Company devices may block it completely.

Do not turn off SmartScreen or antivirus. Instead, check the download first:

1. Download the installer **and** `checksums.txt` (plus `VERIFY.md` for details).
2. In PowerShell, in the download folder:
   ```powershell
   (Get-FileHash .\OpenWorld-Moments_0.1.0-alpha.32_Windows_x64-setup.exe -Algorithm SHA256).Hash.ToLowerInvariant()
   ```
   The value must equal the installer's line in `checksums.txt`.
3. Optional, with the GitHub CLI: confirm the file was built by this repository's CI.
   ```bash
   gh attestation verify OpenWorld-Moments_0.1.0-alpha.32_Windows_x64-setup.exe --repo heetdalsania/openworld-moments
   ```
4. Only then choose **More info → Run anyway** in SmartScreen.

The installer is per-user: it installs under `%LOCALAPPDATA%\OpenWorld Moments` and needs
no administrator rights. Microsoft Edge WebView2 (built into Windows 11) is required.

## What has been tested, and how

We separate three kinds of statements. Only the first are tested facts.

### Tested facts

On a **clean physical Windows 11 x64 laptop** (Windows 11 Home 26H2, Intel Core
i5-1135G7, 8 GB, administrator account with UAC on), the M29 candidate
`0.1.0-alpha.29` completed: checksum verification, install without elevation, the
first-run system check, import, playback, session grouping, a project with a trim,
privacy review, a horizontal 1080p render that played in Windows Media Player,
model download/resume/remove, uninstall with library retention, reinstall and
disposable data removal ([M29 client report](https://github.com/heetdalsania/openworld-moments/blob/main/docs/milestones/M29-windows-client-report.md)).

For **this exact 0.1.0-alpha.32 installer**, the evidence is automated, on GitHub's
hosted Windows Server 2025 runner (not a clean Windows 11 PC):

- silent install into a Unicode folder, with development overrides pointing at missing
  tools so only the bundled runtime can work;
- the real installed WebView2 window driving the bundled worker: system check, first-run
  setup, import of a synthetic clip, playback preparation, session grouping, a project,
  privacy review, and **both a 16:9 (1920×1080) and a 9:16 (1080×1920) render**;
- repair, upgrade to a test-only higher version, and silent uninstall, each keeping the
  library and leaving the database byte-identical;
- an SBOM verified against every packaged file, a scan for secrets and build-machine
  paths, a repeated frozen build with identical payload hashes, and a signed GitHub
  build-provenance attestation for every release file.

The full automated suite (format, lint, type checks, about 1,300 worker tests, desktop,
contract and Rust tests, dependency, license and secret scans, CodeQL) passed for the
release commit.

### Experimental

- Event detection (wanted-indicator changes, on-screen banners and subtitles through
  optional local OCR, audio onsets and speech activity) and story suggestions work on
  **synthetic test media only**. Their quality on real gameplay is **unmeasured**.
- Optional speech transcription needs a separately installed whisper.cpp program; its
  recognition quality is unmeasured.
- FCPXML export is experimental; OpenTimelineIO, SRT, WebVTT, CSV and JSON exports are
  tested against their specifications and validators.
- Hardware video encoders are used only after a passing test encode; the bundled FFmpeg
  build has none, so renders use the CPU encoder (libx264).

### Not claimed

- **No GTA VI (or GTA V) compatibility is claimed.** No game profile has published
  metrics from legally obtained gameplay footage. The `open-world-vi` profile is an
  unvalidated placeholder; see [detector metrics](https://github.com/heetdalsania/openworld-moments/blob/main/docs/releases/0.1.0-alpha.32/detector-metrics.md).
- Windows 10, Windows on Arm, macOS and Linux are not supported by this release.
- No formal accessibility (WCAG) certification; screen-reader testing on Windows is
  still to be done.

## Checks not run on clean Windows hardware for this release

No clean Windows machine was available for M32. The maintainer **waived** the
clean-machine runs below; they are collected in the non-blocking
[M40 — Deferred device verification](https://github.com/heetdalsania/openworld-moments/blob/main/docs/milestones/M40-windows-deferred-verification.md)
and have **not** happened:

- the full import → session → event review → edit → 16:9 and 9:16 render journey with
  this 0.1.0-alpha.32 installer on a clean Windows 11 PC;
- a standard (non-administrator) account install, including the phone-transfer
  firewall prompt;
- SmartScreen behaviour for a browser download;
- phone transfer of several videos in one session (fixed in #38, tested automatically);
- one-click cancel of a model download (fixed in #37, tested automatically);
- Narrator and NVDA screen-reader smoke tests;
- current Xbox and PlayStation transfer steps against the live console apps;
- installing from this GitHub release page after publication (post-publication smoke test).

## What is new since the M29 candidate

- **Security:** rate limits, lockout and Origin checks on the phone upload page; capped
  request sizes; dependency, secret, license and CodeQL gates; an SBOM, provenance
  attestation and verification guide with every package.
- **Onboarding and accessibility:** first-run setup; phone transfer and model downloads
  are off until you turn them on; keyboard-complete import-to-render with **Show in
  folder**; screen-reader announcements; light, dark and high-contrast themes, 200% text
  and reduced motion; a redacted, previewed diagnostics report; versioned user guides.
- **Fixes:** a second phone upload no longer fails with "out of space" (#38); cancelling a
  model download completes in one click and the message says the partial download is
  kept (#37).
- The system check also shows this computer's platform and architecture.

## Upgrading, migration and rollback

- **From nothing:** install normally. Your library lives in
  `%APPDATA%\org.openworldmoments.desktop\library`.
- **From the 0.1.0-alpha.29 test candidate:** run the new installer; it upgrades in
  place and keeps your library. There is **no database migration** in this release
  (schema stays at version 19). Library documents now use contract version 1.27; all
  earlier 1.x documents remain readable. After upgrading, turn phone transfer and model
  downloads back on in **Settings → Privacy choices** if you used them.
- **Rolling back:** the installer refuses to install an older version over a newer one.
  Older builds are not guaranteed to open a library that a newer build has used. Before
  upgrading any alpha, quit the app and copy the library folder; to roll back, uninstall
  (keep your data unticked), restore that copy, and install the older build.
  Details: [rollback and triage](https://github.com/heetdalsania/openworld-moments/blob/main/docs/releases/0.1.0-alpha.32/rollback-and-triage.md).
- There is no automatic update. Check each new release's checksums before installing.

## Privacy

No account, no telemetry, no analytics and no cloud processing. Everything stays on your
computer unless you choose to: open the phone upload page (local network only, plain
HTTP protected by a secret link), download an optional speech model from the signed
catalog, or export a diagnostics report you have previewed. Full statement:
[privacy statement](https://github.com/heetdalsania/openworld-moments/blob/main/docs/releases/0.1.0-alpha.32/privacy-statement.md).

## Files in this release

| File | What it is |
|---|---|
| `OpenWorld-Moments_0.1.0-alpha.32_Windows_x64-setup.exe` | The per-user installer (unsigned) |
| `checksums.txt` | SHA-256 of every other file |
| `sbom.cdx.json` | CycloneDX 1.6 software bill of materials |
| `VERIFY.md`, `SECURITY.md` | How to verify this release; how to report a vulnerability |
| `THIRD_PARTY_NOTICES.txt`, `runtime-notices.zip` | License notices |
| `runtime-inventory.json` | Every packaged runtime file with its hash, pinned sources and tool versions |
| `ffmpeg-*.tar.xz`, `x264-*.tar.gz`, `build-media.sh`, `sources.json`, `compiler.txt`, `build-packages.txt`, `freeze-worker.py`, `runtime_bundle.py`, `python-notices.json` | Corresponding source and build inputs for the GPL FFmpeg/x264 binaries and the frozen worker |
| `native-*.json`, `reproducibility.json` | The automated install, render, repair, upgrade, uninstall and reproducibility reports |

The application is AGPL-3.0-or-later; the bundled FFmpeg and x264 are GPL-2.0-or-later
with their source included; contracts and profiles are Apache-2.0.

## Known limitations

See [known limitations](https://github.com/heetdalsania/openworld-moments/blob/main/docs/guides/known-limitations.md).
The most important: unsigned installer, Windows 11 x64 only, English only, no automatic
updates, captions are not yet burned into renders, detection quality on real games is
unmeasured, and phone transfer uses plain HTTP on your local network.

## Reporting problems

- Bugs: [open an issue](https://github.com/heetdalsania/openworld-moments/issues/new/choose)
  with the version `0.1.0-alpha.32`. Never attach leaked or pre-release footage, game
  files or official assets; a diagnostics report (previewed and redacted by the app) is
  the most useful attachment.
- Security problems: follow [SECURITY.md](https://github.com/heetdalsania/openworld-moments/blob/main/SECURITY.md),
  not a public issue.
