# M29 — Windows 11 client qualification report

This is a **clean Windows 11 client run** on a physical laptop, executed with the
[client runbook](./M29-windows-client-runbook.md) and the
[session prompt](./M29-windows-session-prompt.md). It is separate from hosted CI:
the Windows Server CI job only built the candidate; every result below comes from
the shipped installer on the test laptop.

**Overall result: not fully passed.** Section 8 (M10 real-phone upload) has one
failure: a ~2 MB iPhone video was refused with "out of space" while about 181 GB
was free. Steps 6.2 and 6.3 are recorded as **Pass by maintainer decision**
because they were executed inside a virtualized container (see
[Test-process deviation](#test-process-deviation-sandboxed-installer-runs)).
M29 and M10 stay **In progress**.

## Machine and environment

| Item | Value |
|---|---|
| OS | Windows 11 Home, Version 26H2, OS Build 26300.9711 (read from `winver`), 64-bit |
| Processor | Intel Core i5-1135G7, `Win32_Processor.Architecture` = 9 (x64) |
| RAM | 8,344,559,616 B (~7.8 GiB) |
| Account | **Local administrator account with UAC on** (accepted exception). `S-1-5-32-544` present only as "Group used for deny only" (unelevated); `EnableLUA`=1, `ConsentPromptBehaviorAdmin`=5, `PromptOnSecureDesktop`=1. Every step ran unelevated; nothing used "Run as administrator". |
| WebView2 Runtime | 157.0.4341.46 (EdgeUpdate `pv`); app reports UA Chrome/157.0.0.0 Edg/157.0.0.0 |
| Developer tools on PATH | none. `python`/`python3` are the 0-byte Windows Store aliases (no Python installed); `py`, `uv`, `node`, `pnpm`, `ffmpeg`, `ffprobe`, `tesseract`, `bash`, `gcc` absent |
| Tools installed for the run | GitHub CLI 2.103.3 and Git for Windows 2.56.0.4 via `winget` (default "Git from the command line" PATH option). One UAC prompt was approved for the **Git** installer (setup tool, not the app). |
| Network | Wi-Fi; category Public for sections 1–7, switched to **Private** by the tester for section 8 |
| App-data folder before step 1 | absent |

Behaviours this administrator-account run **cannot show** for a standard user:

1. Whether a standard user can approve the M10 Windows Firewall prompt (normally
   needs administrator credentials). In this run no firewall prompt appeared at all.
2. WebView2 repair, which needs administrator rights.

## Candidate

| Item | Value |
|---|---|
| CI run | 42960417930 (PR #37, "Desktop production build (Windows)" passed in 9m45s) |
| Commit | `778d11e5bc465aee5c2a62b972a5f0e20a8b78b4` |
| Candidate | `OpenWorld-Moments_0.1.0-alpha.29_Windows_x64-setup.exe` — SHA-256 `62afdee80c20372b80173bba2506c0ee97e18824577a5ddbe6e6d7c9c4bf8dbe` = `checksums.txt` |
| Upgrade test | `OpenWorld Moments_0.1.0-alpha.29.1_x64-setup.exe` — SHA-256 `984609353b23ceac7e33cad4727c32d24d764e166442e426724026c7f31dd78d` = `SHA256SUMS.txt` |
| Signing | Authenticode **NotSigned** (unsigned alpha candidate) |

## 1. Preflight — Pass

| Step | Expected | Observed | Result |
|---|---|---|---|
| Windows 11 x64 | Windows 11, arch 9 | Windows 11 Home 26H2 build 26300.9711, arch 9 | Pass |
| UAC | `EnableLUA` = 1 | 1 (admin account, accepted exception) | Pass |
| Clean PATH | no dev tools except Git | only Store `python` aliases (recorded) | Pass |
| WebView2 | present | 157.0.4341.46 | Pass |
| App data | absent before step 1 | absent | Pass |

## 2. Download and verify — Pass

| Step | Expected | Observed | Result |
|---|---|---|---|
| Download both artifacts with `gh run download` | files present | both downloaded | Pass |
| Candidate hash | matches `checksums.txt` | match | Pass |
| Upgrade-test hash | matches `SHA256SUMS.txt` | match | Pass |

## 3. Install and first launch — Pass

| Step | Expected | Observed | Result |
|---|---|---|---|
| Double-click installer in File Explorer | record unsigned prompts; no UAC | **No SmartScreen and no UAC**; NSIS Welcome page directly. The `gh` download carries no Mark-of-the-Web (`Zone.Identifier`), so SmartScreen did not evaluate it; a browser download would likely show "Windows protected your PC". | Pass |
| Default location | under `%LOCALAPPDATA%` | `%LOCALAPPDATA%\OpenWorld Moments`; per-user HKCU uninstall entry "OpenWorld Moments" 0.1.0-alpha.29, publisher "openworldmoments"; Start menu shortcut | Pass |
| Launch from Start menu | app opens | opened in ~5–10 s, no prompts | Pass |
| First-run system check | appears; core checks pass | "Windows / AMD64 · Packaged runtime", "Core checks passed": PASS storage, permissions, loopback, sqlite, codecs, cpu-encode, models (catalog signature), inventory; WARN acceleration (CPU libx264 fallback) | Pass |
| Runtime inventory | versions/hashes recorded | Python 3.12.14; SQLite 3.53.1; worker 0.0.0 / 6244e027c963 (sha256 `06e6fe64…4721d`); ffmpeg 9.0.2 (`462f1463…691dd`); ffprobe 9.0.2 (`eb9ff84b…c071c9b`) — all match on-disk hashes | Pass |
| WebView2 in Settings | version shown | Chrome/157.0.0.0 Edg/157.0.0.0 (OS-managed) | Pass |

## 4. Import, playback, project, render — Pass

| Step | Expected | Observed | Result |
|---|---|---|---|
| 4.1 Synthetic clip with bundled ffmpeg (full path) in a Unicode folder | clip created | `Synthetic ✓ 日本語\Synthetic capture ✓.mp4`, 8,045,331 B, created in ~4 s; SHA-256 `91d030393c2cade397bb229fd4fd929cf5dc8750862ef8eb5759611abe8a75d2` | Pass |
| 4.2 Import button | imported; playback prepared | "1 imported"; "proxy not needed, filmstrip created, waveform created" within a few seconds (no app log files exist to time from) | Pass |
| 4.2 Drag-and-drop | handled | drop zone shown; "1 already in the library"; still 1 clip | Pass |
| 4.2 Clip-view playback | video + audio | video and 440 Hz tone (tester) | Pass |
| 4.2 Session playback | video + audio | after "Group clips into sessions": 1 session, Suggested, confidence 25%; video and tone (tester) | Pass |
| 4.3 Project from session + trim | project created, trimmed | "Untitled story" from session range 0–20000 ms; trim source 2000–15000 ms → Cut 0:13.00, revision 2 | Pass |
| 4.3 Privacy review | review completes | 1 finding `mixed_audio` (audio_metadata, score 0.35); decision "Acknowledge risk" + reviewer checkbox → "Review recorded for this saved revision" | Pass |
| 4.3 Export horizontal 1080p30, CPU (libx264) | Ready | **~10 s** for 13 s output; "Ready · horizontal-1080p30 · libx264 · revision 2", 13/13 checks passed | Pass |
| 4.4 Source hash | unchanged | unchanged | Pass |
| 4.4 Export exists and plays | file plays in Media Player | 9,548,532 B; H.264 1920×1080 30/1 + AAC, 13.000 s; played in Windows Media Player | Pass |

## 5. Model manager — Pass (with notes)

| Step | Expected | Observed | Result |
|---|---|---|---|
| 5.1 Install `tiny.en` | download, verify, active | "Verified installed" in ~10 s; active version `921e4cf8686f` | Pass |
| 5.2 `base.en`, Wi-Fi off mid-download | readable error; partial not active | first attempt completed (~15 s) before Wi-Fi could be switched off; second attempt: "failed: Downloading base.en (5%) — Download could not finish. Retry to resume safely." Not installed; 8,650,752 B `.part` kept | Pass |
| 5.2 Wi-Fi on, Retry | resumes | "Resume install base.en": `.part` stayed at 8,650,752 B (never truncated) then completed; "Verified installed" (`a03779c86df3`). **Bytes resumed** — the downloader requests `Range: bytes=<offset>-` | Pass |
| 5.3 Start with Wi-Fi off | readable offline error; nothing active | "failed: Model installation — Download could not finish. Retry to resume safely." Nothing activated. Note: message is readable but does not say the computer is offline. | Pass |
| 5.4 Cancel in progress | partial kept, not active | partial 49,545,216 B (33%) kept, not active; Settings shows "cancelled … (33%)" with **Resume install**. **Notes:** (a) the Cancel button in Settings stopped the transfer but the job stayed "Working"/"analyzing 33%" until Cancel was clicked again in Background jobs; (b) Background jobs then said "Cancelled. Nothing partial was kept." although the partial was kept on disk (message inaccurate). | Pass (UI defects noted) |
| 5.5 Remove `base.en` | removed; media/transcripts stay | confirmation "Remove this model, its saved versions and unfinished download? Media and transcripts stay in your library." → removed incl. partial; `tiny.en`, clip and render intact | Pass |
| 5.6 Low disk, checksum/signature refusal | covered by automated tests | not exercised on this machine; covered by `services/media-worker/tests/transcripts/test_downloads.py`: `test_bundled_signature_and_tampering`, `test_low_disk_and_offline_preserve_active_model`, `test_corruption_oversize_and_wrong_ranges_never_install`, `test_same_size_corruption_is_not_reported_installed` | Covered by tests |
| Optional engine | recorded | Transcript panel: "Install whisper.cpp (whisper-cli) to enable optional local transcription." — unavailable (expected, not bundled) | Recorded |

## 6. Repair, upgrade, retention

| Step | Expected | Observed | Result |
|---|---|---|---|
| 6.1 Baseline | DB hash, counts | app quit; `database.sqlite3` 528,384 B, SHA-256 `213f46349f5ed8d7879173c79b00de9d82307b7a1358dcf39b183288230de5aa`, `user_version` 19; UI: 1 clip, 1 project (revision 2), 1 render; no backup files | Pass |
| 6.2 Repair (same candidate) | library/project/export intact | "Already Installed" → "Add/Reinstall components" → default location → Installing → Completing; no SmartScreen/UAC. Library, project revision 2 and export (Ready, 13/13) intact; DB hash unchanged. **Executed in Claude's virtualized container — see deviation.** | **Pass by maintainer decision** |
| 6.3 Upgrade to 0.1.0-alpha.29.1 | new version; data and `tiny.en` intact; backup or no-migration recorded | "Already Installed: An older version … recommended that you uninstall the current version before installing" (default "Uninstall before installing") → Installation Complete; no UAC. Footer "Version 0.1.0-alpha.29.1"; clip, project, export and active `tiny.en` intact; `user_version` 19 before and after and DB hash unchanged → **no migration ran**, so no pre-upgrade backup was needed. **Executed in Claude's virtualized container — see deviation.** The same retention was later confirmed on the real system in 7.2. | **Pass by maintainer decision** |
| 6.4 Source hash | unchanged throughout | unchanged | Pass |

## 7. Uninstall, reinstall, data removal — Pass

| Step | Expected | Observed | Result |
|---|---|---|---|
| 7.1 Uninstall from Settings → Apps, app-data **unchecked** | install folder gone; library and DB hash unchanged | Settings "This app and its related info will be uninstalled." → NSIS "Uninstall OpenWorld Moments", "Delete the application data" unchecked → "Uninstallation Complete"; no UAC. Install folder, Start menu and desktop shortcuts gone; Settings no longer lists the app; library kept (12 files), DB hash unchanged | Pass |
| 7.2 Reinstall 0.1.0-alpha.29.1 | same library, project, export | Tester double-clicked the installer in File Explorer and launched from Start: Settings lists 0.1.0-alpha.29.1; worker started; 1 clip, project revision 2, export Ready 13/13; `user_version` 19, DB hash unchanged. (An earlier reinstall attempt inside the virtualized container opened with "Worker unavailable: No worker is configured for this build. Set OWM_WORKER_PYTHON or run a debug build." — attributed to the container, not reproduced on the real system.) | Pass |
| 7.3 Disposable removal | tester confirms disposable; uninstall **with** app data; confirmations list consequences; library removed; source kept | Tester confirmed the library is disposable. "Delete the application data" ticked, then one confirmation dialog (the installer hook's dialog lists the library, projects, transcripts, downloaded models and managed media; external footage kept; preferences retained — tester did not capture a screenshot). Library removed (the `%APPDATA%\org.openworldmoments.desktop` folder remains, empty); `%LOCALAPPDATA%\org.openworldmoments.desktop\EBWebView` retained (preferences/WebView data, expected); synthetic source clip hash unchanged | Pass |

## 8. M10 real-phone upload — **Fail**

Reinstalled 0.1.0-alpha.29.1 from File Explorer (new empty library), network
category **Private**. Phone: **iPhone 13, iOS** (browser not recorded; opened from the camera QR scan).

| Step | Expected | Observed | Result |
|---|---|---|---|
| 8.1 Import from phone → Wi-Fi interface → Show QR code; firewall prompt | QR shown; record firewall prompt; allow private only | QR and "Closes in 10:00" shown. **No Windows Firewall prompt appeared** anywhere (administrator account). | Pass |
| 8.2 Upload two videos + one non-video | videos progress and are added | one video recorded on the spot (~190 KB `.MOV`) uploaded and "Added to the library". A second video of **~2 MB** was refused on the phone with **"out of space"** twice; the laptop had ~181 GB free. The refused upload is not shown on the desktop list. | **Fail** |
| 8.3 Non-video refused | refused | the iOS picker did not offer photos, so no non-video file could be sent; server-side refusal not exercised on the phone | Not exercised |
| 8.3 Re-send a video | "Already in the library" | tester: re-sending worked as expected; still one entry on the desktop | Pass |
| 8.4 "I'm done", reload | link inactive | phone showed it could leave the page; the upload port stopped listening and the old link could not be reached | Pass |
| 8.4 Reopen screen, close it | old link must not work | desktop then showed "The phone finished the session."; a new session's link stopped listening as soon as the screen was left; old link still unreachable | Pass |
| Note | — | after "I'm done" the desktop kept showing the QR code with "Closes in 0:00" and a disabled "Close upload page" button until the screen was left | UI defect |

**Failure detail (8.2):** phone message "The computer is out of space."
(`disk_full`). Free space on the library volume was ~181 GB, far above the 1 GiB
margin in `gateway/uploads.py`. A plausible cause, not verified here:
`gateway/app.py` sets `free = 0` when `shutil.disk_usage(session.staging)` raises
`OSError`, which turns any such error into `disk_full`. No application log
folder exists, so no logs could be collected.

## Test-process deviation: sandboxed installer runs

The Claude desktop app that drove this run is an MSIX-packaged app. Installers
started from its shell (`Start-Process`) and app windows opened by its
computer-use tool ran inside the package container, so their `%LOCALAPPDATA%`
and HKCU writes were redirected into the package's private store. This affected
the repair (6.2), the upgrade (6.3) and a first reinstall attempt (7.2). Evidence:
Windows Settings kept listing 0.1.0-alpha.29 while the container saw
0.1.0-alpha.29.1, and an uninstall entry remained visible only inside the
container after the real uninstall. The roaming library was **not** redirected
(database hash and schema stayed the same throughout). Sections 1–5, 6.1, 7.1,
7.2 (real reinstall), 7.3 and 8 ran outside the container: installers were
double-clicked in File Explorer and the app was launched from the Start menu.
The maintainer chose not to repeat 6.2 and 6.3 and accepted them as run.
Future runs must start every installer from File Explorer and the app from the
Start menu.

## Timings

| Operation | Time |
|---|---|
| Synthetic clip creation (bundled ffmpeg) | ~4 s |
| Import + playback preparation (8 MB, 20 s 720p) | a few seconds (tester observation) |
| Export 13 s horizontal 1080p30 libx264 | ~10 s |
| `tiny.en` download + verify (75 MiB) | ~10 s |
| `base.en` download + verify (142 MiB) | ~15 s |

## Failures and defects

1. **Fail (8.2):** a ~2 MB iPhone video was refused with "The computer is out of
   space." while ~181 GB was free (reproduced twice).
2. Defect (5.4): Background jobs says "Cancelled. Nothing partial was kept."
   although the partial download is kept (and Settings offers Resume).
3. Defect (5.4): Cancel in Settings stopped the transfer but left the job
   "Working" until cancelled again from Background jobs.
4. Defect (8.4): after the phone finishes, the desktop keeps showing the QR code
   with "Closes in 0:00" until the screen is left.
5. Note (5.3): the offline download error does not mention being offline.
