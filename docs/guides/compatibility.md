# Compatibility notes

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31).

This page is versioned with the app. Each release adds a section; older sections stay
for reference.

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
