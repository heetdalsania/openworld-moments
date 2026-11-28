# Using OpenWorld Moments on a Mac

> **Applies to:** OpenWorld Moments 0.1.0 preview for macOS 14 or later (Apple Silicon and Intel).
> **Last checked:** 2026-11-28 (M38). See [Validation](#validation).

> **macOS builds are previews.** They are not a supported release and not for general
> download yet. A Mac download becomes available only when it is signed with a
> Developer ID and notarized by Apple, which is planned for the dual-platform release
> (M39). Until then, macOS builds go only to project testers. If you were given a Mac
> build and macOS refuses to open it, don't try to get around the warning: see
> [If macOS won't open the app](#if-macos-wont-open-the-app).

Everything in the [other guides](./README.md) works the same on a Mac. This page covers
what is different: which download to pick, installing, macOS permission prompts, the
menu bar, updating, removing the app, and where your data lives. None of it needs
Terminal.

## Which download?

There are two Mac downloads, one for each kind of processor. Each runs natively, with no
Rosetta.

1. Choose **Apple menu → About This Mac**.
2. Look at the first line:

| About This Mac shows | Download |
|---|---|
| **Chip:** Apple M1, M2, M3, M4 or later | `OpenWorld-Moments_<version>_macOS_arm64.dmg` (Apple Silicon) |
| **Processor:** Intel | `OpenWorld-Moments_<version>_macOS_x86_64.dmg` (Intel) |

Both need macOS 14 Sonoma or later. Next to the downloads are `checksums.txt` (to check a
download, see [release verification](../security/release-verification.md)), the software
bill of materials and the third-party notices.

If you picked the wrong one, the app tells you. **Settings → System check** shows
*Right download for this Mac*; the Intel build on an Apple Silicon Mac also says it is
running through Rosetta and should be replaced with the Apple Silicon download.

## Install

1. Download the DMG for your Mac (see above) and open it.
2. Drag **OpenWorld Moments** onto the **Applications** folder in the window that opens.
3. Eject the disk image (**File → Eject** in Finder).
4. Open **OpenWorld Moments** from Launchpad or the Applications folder.
5. A notarized release shows the usual question for apps from the internet:
   *“OpenWorld Moments” is an app downloaded from the Internet. Are you sure you want to
   open it?* Choose **Open**. You see this once.
6. First-run setup starts (next section).

Steps 1 and 5 can only be checked with a notarized download; that check is part of the
dual-platform release (M39).

### If macOS won't open the app

If macOS says the app *can't be opened*, *is damaged*, *can't be checked for malicious
software*, or offers to move it to the Trash, that copy is not a notarized release.
**Don't work around the warning** and don't change any security setting. Move the copy
to the Trash, and download a notarized release from the project's GitHub Releases page
once one is published. The app never asks you to lower your Mac's security.

## First-run setup

Setup has seven short steps on a Mac. Each one can be skipped and changed later in
**Settings**:

1. **Welcome:** what the app does and does not do.
2. **Check this computer:** macOS version, which build you have (Apple Silicon or
   Intel), whether it is the right one, how this copy is signed, and the storage and
   tool checks.
3. **What macOS may ask:** the permission prompts described below, before you see them.
4. **How your clips get here.**
5. **Privacy choices:** phone transfer and model downloads stay off until you turn them
   on.
6. **Display and motion.**
7. **Done.**

## Permissions and recovery

macOS asks before an app reads some places or uses your network. OpenWorld Moments asks
only when you use a feature that needs it. It never needs **Full Disk Access**, and every
fix below is to *allow OpenWorld Moments* somewhere: none of them turns a protection
off. The same explanations are in the app under **Settings → macOS permissions**, with
buttons that open the right System Settings page.

| When | What macOS asks | What to do | If you refused |
|---|---|---|---|
| You import from, or watch, Desktop, Documents or Downloads | *“OpenWorld Moments” would like to access files in your … folder* | **Allow** | **System Settings → Privacy & Security → Files and Folders**, turn on the folder for OpenWorld Moments, then choose the folder again in the app. |
| You import from an external drive or SD card | *… would like to access files on a removable volume* | **Allow** | Same place: turn on *Removable Volumes*. |
| You import from a network drive | *… would like to access files on a network volume* | **Allow** | Same place: turn on *Network Volumes*. |
| You open **Import from phone** the first time | *… would like to find devices on your local networks* | **Allow** | **Privacy & Security → Local Network**, turn on OpenWorld Moments, then open **Import from phone** again. |
| The macOS firewall is on and the phone page opens | *Do you want the application “OpenWorld Moments” to accept incoming network connections?* | **Allow**. Keep the firewall on. | **System Settings → Network → Firewall → Options**, set OpenWorld Moments to *Allow incoming connections*. |

Phone transfer only listens on the address you choose, only while its page is open, and
closes when your Mac sleeps. See [PlayStation and phone clips](./phone-upload.md).

### Folders that become unavailable

| What you see | Why | What to do |
|---|---|---|
| A watched folder or clip says it needs access again | macOS access was turned off, or the folder was replaced | Open **Settings → Watched folders** and choose **Select folder again…** for that folder; pick the same folder. Your clips and edits stay. |
| Clips on an external drive show as unavailable | The drive is disconnected | Reconnect it. Nothing was deleted, and the clips come back. |
| Clips from OneDrive or iCloud Drive say *Download required* | The files are kept only in the cloud | In Finder, select the folder and choose **Download Now**, or **Always Keep on This Device** (OneDrive). Then import again. |
| The library can't be found after you moved it | The library was moved while the app was closed | **Settings → Library location → Choose existing library…**, then reopen the app. |

## Getting clips onto your Mac

- **Xbox:** turn on OneDrive backup for captures on the console, install the OneDrive app
  for Mac, keep the captures folder on this Mac, and add it as a watched folder. See
  [Xbox through OneDrive](./xbox-onedrive.md).
- **PlayStation:** download clips to your phone with the PlayStation App, then use
  **Import from phone**. See [PlayStation and phone clips](./phone-upload.md). From an
  iPhone you can also AirDrop clips to the Mac and import them from Downloads.
- **USB drives, SD cards and capture cards:** import from the drive, or copy into the
  library (managed import) if the drive won't stay connected. See
  [Capture cards and PC recordings](./capture-card.md).

## Menus and keyboard shortcuts

The Mac version has the standard menu bar. **Help → Keyboard Shortcuts** (⌘/) lists them
all in the app.

| Menu | Item | Keys |
|---|---|---|
| OpenWorld Moments | About OpenWorld Moments (version) | |
| | Settings… | ⌘, |
| | Hide, Hide Others, Show All | ⌘H, ⌥⌘H |
| | Quit OpenWorld Moments | ⌘Q |
| File | Import… | ⇧⌘I |
| | Import from Phone… | |
| | New Project from Session… | ⌘N |
| | Open Recent | |
| | Show Library in Finder | ⇧⌘R |
| | Close Window | ⌘W |
| Edit | Undo, Redo, Cut, Copy, Paste, Select All | ⌘Z, ⇧⌘Z, ⌘X, ⌘C, ⌘V, ⌘A |
| | Find… | ⌘F |
| View | Library, Sessions, Projects, Search | ⌘1, ⌘2, ⌘3, ⌘4 |
| | Show Background Jobs | ⌥⌘J |
| | Make Text Bigger, Make Text Smaller, Actual Size | ⌘=, ⌘-, ⌘0 |
| | Enter Full Screen | ⌃⌘F |
| Window | Minimize, Zoom, Bring All to Front | ⌘M |
| Help | OpenWorld Moments Help, Using OpenWorld Moments on a Mac | |
| | Keyboard Shortcuts | ⌘/ |
| | Save Diagnostics Report…, Run Setup Again | |

The in-app shortcuts are the same as on Windows with ⌘ instead of Ctrl: **/** or **⌘K**
opens Search, and the editor uses **⌘Z**, **⇧⌘Z** and **⌘S**. See
[Accessibility](./accessibility.md#keyboard-shortcuts).

**Quitting** with ⌘Q, **Close Window** or the window's close button asks first if
background jobs are still running or project edits haven't been saved. Interrupted jobs
continue, or can be retried from **Background jobs**, when you reopen the app. Quitting
from the Dock or by logging out doesn't ask.

## Finding your videos

- After a render, choose **Show in Finder** in the Export panel. Finder opens with the
  video selected.
- **File → Show Library in Finder** (⇧⌘R) opens the library folder.

## Update

There is no automatic updater.

1. Quit OpenWorld Moments (⌘Q).
2. Download the new DMG for your Mac and open it.
3. Drag **OpenWorld Moments** onto **Applications** and choose **Replace**.

Your library, projects, settings and folder permissions are kept: they live outside the
app. An older version refuses a library a newer one has upgraded, rather than damaging
it; the library is backed up before every upgrade.

## Uninstall

1. Quit OpenWorld Moments.
2. Drag **OpenWorld Moments** from **Applications** to the Trash.

That removes the app only. Your library, settings and logs stay, in case you reinstall.
To remove them too, which is **permanent**, delete these folders in Finder
(**Go → Go to Folder…**):

| Folder | Holds | Safe to delete? |
|---|---|---|
| `~/Library/Application Support/OpenWorld Moments/` | Library database, settings, managed copies of imported clips, renders | Only if you want to lose your library and projects |
| `~/Library/Caches/OpenWorld Moments/` | Playback copies, thumbnails, analysis caches | Yes; they are rebuilt |
| `~/Library/Logs/OpenWorld Moments/` | Redacted diagnostic logs | Yes |

Original clips imported by reference are never in these folders and are never deleted. A
library you moved elsewhere stays where you put it. The full details are in
[macOS signing and packaging](../platforms/macos-signing.md#install-upgrade-replace-and-uninstall).

## Privacy on a Mac

- Everything runs on your Mac. There is no account, no analytics, and nothing is
  uploaded.
- Your library stays in your user's Library folder (above). The app reads other files
  only when you choose them, and macOS asks you first for protected places.
- Phone transfer and model downloads are off until you turn them on.
- Logs are redacted (no file names, paths or tokens) and rotate.
- A [diagnostics report](./diagnostics.md) shows its full contents before you save it.
  On a Mac it adds your macOS version, which build you have, and how the app is
  signed. It never names you, your files or folders.

## Diagnostics

**Help → Save Diagnostics Report…** opens the report in Settings. See
[Diagnostics for support](./diagnostics.md). The `signing` part says how this copy of the
app is signed, as macOS itself reports it:

| `state` | Meaning |
|---|---|
| `notarized` | Signed with a Developer ID and accepted by Gatekeeper as notarized: a release |
| `developer-id` | Signed with a Developer ID but **not** notarized |
| `adhoc` | Signed for testing only (preview and CI builds); not notarized |
| `unsigned`, `other` | Not a release build |
| `unknown` | macOS could not be asked (the check timed out) |

The report never claims notarization unless Gatekeeper accepted the app as notarized.

## Accessibility on a Mac

VoiceOver, Voice Control, Full Keyboard Access, Increase contrast, Reduce motion and
zoom are covered in [Accessibility](./accessibility.md#macos).

## Validation

| Part | How it was checked | Date |
|---|---|---|
| Which download, system check wording | Automated tests of the architecture recommendation and the guide links | 2026-11-28 |
| Menus, shortcuts, Quit question | Automated tests of the menu layout and actions; the installed ad hoc build on Apple Silicon (see the M38 handoff) | 2026-11-28 |
| Permissions and recovery | Wording matched to the app; automated tests; physical checks are in the M38 handoff | 2026-11-28 |
| Install steps 1 and 5 (browser download, first-launch confirmation) | **Not yet**: needs a notarized DMG (M39) | — |
| Clean user account on Apple Silicon and Intel | See the M38 handoff | — |

If anything here doesn't match what you see, save a [diagnostics report](./diagnostics.md)
and tell us.
