# Xbox captures through OneDrive

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31).

OpenWorld Moments can import your Xbox game clips automatically. It does this
by watching a folder on your computer that OneDrive keeps in sync.

**It does not connect to Xbox Live, your Xbox, or OneDrive.** It never signs in
anywhere, and it never moves, renames, or deletes your files.

## Set up

1. **Get your captures into OneDrive.** On your Xbox, back up or upload your
   game clips to OneDrive. Microsoft explains the current options in
   [Xbox Support: Back up your game captures](https://support.xbox.com/en-US/help/games-apps/my-games-apps/back-up-game-clips).
   The Xbox menus and options are Microsoft's and can change. If they differ
   from this guide, follow Xbox Support.
2. **Install OneDrive on this computer** and sign in with the same Microsoft
   account as your Xbox.
3. **Keep the clips on this computer.** In File Explorer, open your OneDrive
   folder, find the folder where your Xbox clips arrive, right-click it, and
   choose **Always keep on this device**. Otherwise OneDrive may only list the
   clips without downloading them, and OpenWorld Moments waits for the download
   instead of starting it.
4. **Choose the folder in OpenWorld Moments.** Use **Choose Xbox captures folder…**
   in first-run setup, **Choose captures folder…** on the Xbox card in Settings, or
   **Watched folders → Add folder…** with the source set to *Xbox (OneDrive)*. See
   [Watched folders](./watched-folders.md).

## What happens next

- A new clip is imported **after OneDrive finishes downloading it**: once its
  size has stopped changing for about 10 seconds. Large clips take as long as
  OneDrive needs to download them.
- Clips that arrived while OpenWorld Moments was closed are found the next
  time it starts.
- Clips are imported **by reference**: the library points at the file in your
  OneDrive folder. If you later move or delete a clip, OpenWorld Moments shows
  it as missing; it never deletes anything itself.
- The **Watched folders** panel shows how many clips were imported, how many
  are waiting to finish downloading, how many are still only in the cloud, and
  any that failed.

## Limitations

- **Upload is up to you.** Getting clips from the Xbox into OneDrive happens on
  the Xbox side, outside OpenWorld Moments. How and when that happens is up to
  Xbox and OneDrive.
- **Cloud-only clips wait.** Clips that are only in the cloud are not imported
  until OneDrive has downloaded them. This is detected on Windows. On other
  systems, keep the folder downloaded.
- **Some locations are slower.** On a network drive, or anywhere live file
  notifications are not available, new clips are found by a scan every 15
  minutes. The panel then says *Watching (periodic scans only)*.
- **Offline folders retry quietly.** If the folder is unavailable (for example,
  a disconnected drive), OpenWorld Moments checks again with growing intervals
  and resumes on its own when the folder is back.

More technical detail: [Watched folders](../architecture/watched-folders.md).
