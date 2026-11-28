# Compatibility notes

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64), and the macOS 14+ preview.
> **Last checked:** 2026-11-28 (M38).

This page is versioned with the app. Each release adds a section; older sections stay
for reference.

## After 0.1.0-alpha.32: macOS preview (M37–M38)

Not a release. Builds from `main` after `0.1.0-alpha.32` add:

- **macOS 14+ previews** for Apple Silicon (`arm64`) and Intel (`x86_64`), signed ad hoc
  and not notarized, with native menus and macOS setup and permission guidance. See
  [Using OpenWorld Moments on a Mac](./macos.md).
- **Data formats:** contract version **1.28**: the platform report in diagnostics adds a
  `signing` block (how the app is signed; never the signer). 1.27 and older documents
  still read. No database change.
- **Windows:** unchanged, apart from the platform report now saying `menus: "none"`
  (the Windows window has never had a menu bar).

## 0.1.0-alpha.32 — first public alpha (M32)

The first public Windows release. Everything in the section below still applies, with
these changes:

- **Version:** `0.1.0-alpha.32`, an unsigned per-user installer from the GitHub release
  page. Check it with `checksums.txt` before installing.
- **Tested:** this build passed automated install, import, 16:9 and 9:16 render,
  repair, upgrade and uninstall checks on a hosted Windows Server runner. The clean
  Windows 11 PC run was done with the earlier `0.1.0-alpha.29` build; a clean-PC run of
  this build is still to be done.
- **Standard (non-administrator) accounts** are expected to work but are untested.
- **Data formats:** documents use contract version **1.27**; the library database is
  unchanged (version 19), so upgrading from `0.1.0-alpha.29` runs no migration.
- **Games:** no game is listed as compatible yet. See the
  [release compatibility matrix](../releases/0.1.0-alpha.32/compatibility-matrix.md) and
  [detector metrics](../releases/0.1.0-alpha.32/detector-metrics.md).

## 0.1.0 alpha (M29–M31)

### Systems

| | Supported | Notes |
|---|---|---|
| Windows 11 x64 | Yes | Qualified on a clean client in M29. |
| Windows 10 | Not in the alpha | Untested; the alpha targets Windows 11 only. |
| Windows on Arm | No | No Arm build yet. |
| macOS | Not yet | Planned (M33–M38). |
| Linux | No | Development only. |
| WebView2 | Required | Built into Windows 11 and kept up to date by Windows. |

Free space: at least 512 MiB for the app to run, plus room for imports you copy,
playback copies, models and renders.

### Clips

| Item | Supported |
|---|---|
| Containers | MP4, M4V, MOV, MKV, WebM, TS, M2TS, AVI |
| Video | H.264 and HEVC; other codecs FFmpeg can decode usually work through a playback copy |
| HDR | Yes: tone-mapped to standard range for playback and renders |
| Audio | AAC and other FFmpeg-decodable audio; the editor previews the first audio track |
| Phone transfer | MP4, MOV, M4V, MKV and WebM, up to 10 GB per file |

### Sources

| Source | How | Guide |
|---|---|---|
| Xbox | OneDrive folder on this computer, watched | [Xbox through OneDrive](./xbox-onedrive.md) |
| PlayStation | PlayStation App → phone → phone transfer | [PlayStation and phone clips](./phone-upload.md) |
| Capture cards, OBS, PC recordings | Import, or a watched folder | [Capture cards](./capture-card.md) |

Console menus and companion apps belong to Microsoft and Sony and can change. If they
differ from these guides, follow their support pages.

### Output

| Item | Supported |
|---|---|
| Renders | H.264 video, AAC audio, MP4; 16:9 and 9:16 presets |
| Encoders | CPU (libx264) always; hardware encoders only after a passing test encode |
| Open formats | Project JSON, events JSONL, SRT, WebVTT, CSV markers, OTIO; FCPXML experimental |

### Data formats

Library documents use contract version **1.24**. This version reads documents written by
any earlier 1.x version. Older app versions cannot open a library after a newer version
has upgraded it, so keep a backup before trying an older build.

### Changes in this version (M31)

- First-run setup.
- Phone transfer and model downloads now need an explicit opt-in. After updating, turn
  them on again in **Settings → Privacy choices** if you used them before.
- Display settings: theme, text size and reduced motion.
- Diagnostics report.
- **Show in folder** for renders.
