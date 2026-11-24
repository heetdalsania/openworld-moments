# Compatibility matrix — 0.1.0-alpha.32 (Windows)

Every row says **how** it was established. "Clean client" means a physical Windows 11
PC with no developer tools, as in the [M29 client runbook](../../milestones/M29-windows-client-runbook.md).
"Hosted CI" means GitHub's `windows-2025` runner installing the release installer.
"Automated" means repository tests. Anything else is untested.

## Systems

| System | Status | Evidence |
|---|---|---|
| Windows 11 x64 (Home/Pro), administrator account with UAC | **Supported** | Clean client with the M29 build `0.1.0-alpha.29` (Windows 11 Home 26H2 build 26300.9711, Intel i5-1135G7, 8 GB, WebView2 157). This `0.1.0-alpha.32` build: hosted CI only. |
| Windows 11 x64, standard (non-administrator) account | Expected, **untested** | Per-user installer needs no elevation by design. Clean-client run deferred to [M40](../../milestones/M40-windows-deferred-verification.md). |
| Windows Server 2025 x64 | Not supported; used for CI | Hosted CI installs, runs and uninstalls every candidate. |
| Windows 10 | Not supported | Not tested. |
| Windows 11 on Arm | Not supported | No Arm build; x64 emulation untested. |
| macOS 14+ (Apple Silicon, Intel) | Not in this release | Development bundles exist (M33–M36); signed DMGs are M37, qualification M39. |
| Linux | Not supported | Development only. |
| WebView2 | Required, OS-managed | Not bundled. Clean client had 157.0.4341.46. |

## Inputs

| Source | Status | Evidence |
|---|---|---|
| Files and folders by button or drag and drop (MP4, MOV, MKV, M4V, WebM, TS, M2TS, AVI) | Supported | Clean client (M29, MP4); automated probe/import tests for every container. |
| H.264 and HEVC, SDR and HDR (PQ/HLG tone-mapped) | Supported | Automated synthetic FFmpeg fixtures; clean client H.264. |
| Xbox via a OneDrive folder on this PC (watched folder) | Supported, **documentation unverified against the current Xbox app** | Automated watcher tests including cloud placeholders. [Guide](../../guides/xbox-onedrive.md). Live console check deferred (M40). |
| PlayStation via the PlayStation App → phone → phone transfer | Supported, **multi-file retest pending** | Clean client: one iPhone 13 video uploaded (M29). The second-upload "out of space" defect is fixed in #38 with regression tests; hardware retest deferred (M40). |
| Phone transfer (any phone browser on the same private network) | Supported | Automated gateway, threat and E2E tests; clean client (iPhone 13). |
| Capture cards, OBS and PC recordings | Supported as ordinary files | Automated import tests. [Guide](../../guides/capture-card.md). |

## Outputs

| Output | Status | Evidence |
|---|---|---|
| 16:9 H.264/AAC MP4 (`horizontal-1080p30`, CPU libx264) | Supported | Clean client (M29, played in Windows Media Player); hosted CI with this build. |
| 9:16 H.264/AAC MP4 (`vertical-1080x1920-30`, CPU libx264) | Supported | Hosted CI with this build (M32 adds it to the packaged smoke); automated geometry goldens (M25). Not yet on a clean client. |
| Hardware encoders (NVENC, Quick Sync, AMF) | Not available | The bundled minimal GPL FFmpeg build includes none; the system check reports them unavailable. |
| Project JSON, events JSONL, SRT, WebVTT, CSV markers, OpenTimelineIO | Supported | Automated golden and validator tests (OTIO 0.18, `otiostat`). |
| FCPXML | Experimental | Automated structure tests only. |
| Burned-in captions and text overlays | Not available | Recorded in projects, not drawn (renders ask you to confirm the omission). |

## Games and detectors

| Profile | Version | Status |
|---|---|---|
| `generic-wanted` | 1.0.0 | Synthetic validation only |
| `generic-text` (banner/subtitle OCR, optional Tesseract) | 1.0.0 | Synthetic validation only |
| `generic-audio` | 1.0.0 | Synthetic validation only; supporting evidence |
| `generic-open-world` | 1.0.0 | Synthetic SDK example |
| `open-world-vi`, `gta-v` | — | Unvalidated placeholders; **no compatibility claim** |

See [detector metrics](./detector-metrics.md). A game is listed as compatible only after a
profile version is published with its fixture description and measured metrics.

## Data formats

| Item | Value |
|---|---|
| Library database schema | 19 (no migration since M29) |
| Contract (document) version | 1.27; reads all earlier 1.x documents |
| Detector SDK | 1.3.0 |
| Story generator | `owm-story` 1.0.0 |
| Optional speech models (signed catalog) | whisper.cpp `tiny.en`, `base.en` at revision `5359861c739e955e79d9a303bcbc70fb988958b1`, MIT |
