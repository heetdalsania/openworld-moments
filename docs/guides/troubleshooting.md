# Troubleshooting

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64), and the macOS 14+ preview.
> **Last checked:** 2026-11-28 (M38).

Find the message you see, then follow the fix. If nothing here helps, save a
[diagnostics report](./diagnostics.md) and ask for help.

## Installing and starting

| What you see | What to do |
|---|---|
| *Windows protected your PC* (SmartScreen) | The alpha installer is not signed yet. Check the download with `checksums.txt` ([how](../security/release-verification.md)), then choose **More info → Run anyway**. |
| A bar says **Worker: starting…** for more than a minute | The media worker runs in the background and starts with the app. Close the app and open it again. If it keeps happening, run the installer again and choose **Repair**. |
| **Worker: restarting (attempt …)** | The worker stopped and is being restarted. Your jobs are kept and continue afterwards. |
| **Worker unavailable: …** | It could not be restarted. Note the message, run the installer's **Repair**, and save diagnostics if it persists. |
| Security software asks about *owm-worker* or local ports | Allow it. The worker only listens on this computer (loopback) and needs a local port. |

## System check

The system check runs in first-run setup and in **Settings → System check**. Each line
says **Passed**, **Warning** or **Failed**.

| Check | If it fails |
|---|---|
| `storage` | Free up space on the drive with the library; keep at least 512 MiB free, more for imports, models and renders. |
| `permissions` | The library folder must be writable. Check that security software is not blocking `%APPDATA%\org.openworldmoments.desktop`. |
| `loopback` | Allow local loopback ports in security software. |
| `sqlite`, `codecs`, `cpu-encode`, `inventory` | A bundled tool is damaged or missing. Run the installer's **Repair**. |
| `models` | The model catalog failed its signature check. Run **Repair**. |
| `acceleration` (warning) | Hardware encoding is unavailable. Renders use the CPU encoder instead; nothing to fix. |

## Importing

| What you see | What to do |
|---|---|
| *This file type is not supported.* | Import MP4, MOV, M4V, MKV, WebM, TS, M2TS or AVI video. |
| *The file is damaged or incomplete.* | The recording may still be copying or was cut off. Wait for the copy to finish, or re-export it from the source. |
| *The original file is missing, offline, or changed since import.* | A reference import points at a file that moved or is on a disconnected drive. Reconnect the drive or put the file back; the clip then works again. |
| *There is not enough free space in the library folder.* | Free space on the library's drive, then retry the job from **Background jobs**. |
| A watched folder says *Watching (periodic scans only)* | Normal for network drives: new files are found every 15 minutes. |
| OneDrive clips never appear | Mark the OneDrive folder **Always keep on this device**. See [Xbox through OneDrive](./xbox-onedrive.md). |

## Phone transfer

| What you see | What to do |
|---|---|
| *Phone transfer is off* | Choose **Allow phone transfer on this network**, or turn it on in **Settings → Privacy choices**. |
| No network connection is listed | Connect the computer to your home Wi-Fi or Ethernet, then reopen the screen. |
| The phone cannot open the page | Use the same network on both devices, avoid guest networks that isolate devices, and allow the Windows Firewall prompt for **private** networks. |
| *This upload link is not active* | The page closed or expired. Open **Import from phone** again for a new code. |

More in [PlayStation and phone clips](./phone-upload.md#if-something-goes-wrong).

## Playback, editing and rendering

| What you see | What to do |
|---|---|
| A clip shows *Preparing playback media…* | The app makes a playback copy for formats the player cannot show directly (for example HEVC or HDR). Wait for it to finish. |
| A render failed on a hardware encoder | Choose **Render with the CPU encoder instead**. |
| A render failed its checks | The failed checks are listed under the render. Save diagnostics if the reason is unclear. |
| *Model downloads are off* | Allow them in **Settings → Privacy choices** if you want transcription. |
| I can't find my rendered video | Choose **Show in folder** (**Show in Finder** on a Mac) on the finished render, or **Settings → Help and setup → Show library folder** and open `renders`. |

## macOS

The Mac version is a preview; see [Using OpenWorld Moments on a Mac](./macos.md).

| What you see | What to do |
|---|---|
| macOS says the app *can't be opened*, *is damaged* or *can't be checked for malicious software* | That copy is not a notarized release. Don't work around the warning or change security settings. Move it to the Trash and use a notarized release when one is published. See [If macOS won't open the app](./macos.md#if-macos-wont-open-the-app). |
| The system check says the build runs **through Rosetta** | You have the Intel build on an Apple Silicon Mac. Quit, then install the Apple Silicon (`arm64`) DMG over it. See [Which download?](./macos.md#which-download). |
| The system check says the Mac needs a newer macOS | The app needs macOS 14 Sonoma or later. |
| Import says it can't read a folder in Desktop, Documents, Downloads or on a drive | macOS access was refused. **Settings → macOS permissions → Open Files and Folders settings**, turn on OpenWorld Moments for that place, then choose the folder again. |
| A watched folder says it needs access again | **Settings → Watched folders → Select folder again…** and choose the same folder. |
| Clips say *Download required* | They are in OneDrive or iCloud Drive but not on this Mac. In Finder choose **Download Now** (or **Always Keep on This Device**), then import again. |
| The phone can't open the upload page on a Mac | Allow the *find devices on your local network* prompt (or turn OpenWorld Moments on under **Privacy & Security → Local Network**). If the firewall asks about incoming connections, choose **Allow**; keep the firewall on. |
| ⌘Q asks before quitting | Background jobs are running or project edits aren't saved yet. Choose **Cancel** to let them finish, or **Quit**; interrupted jobs continue or can be retried when you reopen the app. |
| The diagnostics report says `"state": "adhoc"` under `signing` | This copy is a test build, not a notarized release. That's expected for previews. |

## Starting over

- **Run setup again:** **Settings → Help and setup → Run setup again**.
- **Mac:** to remove the app, or the app and its data, see [Uninstall](./macos.md#uninstall).
- **Reinstall:** uninstalling keeps your library by default, so a reinstall picks up
  where you left off. Removing the library is a separate, explicit choice in the
  uninstaller.
