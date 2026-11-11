# Watched folders

> **Applies to:** OpenWorld Moments 0.1.0 alpha for Windows 11 (x64).
> **Last checked:** 2026-11-11 (M31).

A watched folder imports new videos on its own: captures that OneDrive syncs from an
Xbox, recordings from capture software, or clips copied to a drive. OpenWorld Moments
only reads the folder. It never moves, renames or deletes anything in it.

## Add a folder

1. Open **Settings** and scroll to **Watched folders**.
2. Choose the **Source** that describes the clips: *Xbox (OneDrive)*, *PlayStation*,
   *OBS*, *Capture card* or *Other*. It labels the clips and helps the app group
   sessions.
3. Choose **Add folder…** and pick the folder.

Videos already in the folder are imported first, then new ones as they arrive.

## How new files are picked up

- A file is imported once its size has **stopped changing for about 10 seconds**, so
  recordings and downloads that are still being written are left alone until they
  finish.
- Files are imported **by reference**: the library points at the file where it is.
  If you later move or delete it, the app shows it as missing.
- Files that arrived while the app was closed are found the next time it starts.
- Hidden files and anything inside hidden folders are skipped.

## Options for each folder

| Option | What it does |
|---|---|
| **Watch this folder** | Untick to pause. A paused folder does no work at all. |
| **Include subfolders** | On by default. Untick to watch only the top level. |
| **File filters** | *Only import files matching* and *Skip files matching* take comma-separated patterns such as `*.mp4` or `raw/**`. Empty means every video. |
| **Show failed files** | Lists files that could not be imported, with the reason. Temporary problems are retried automatically. |
| **Stop watching** | Removes the folder from the list. The folder and its files are not changed. |

## Slow or unavailable folders

- **Network drives**, and other places without live file notifications, are scanned
  every 15 minutes. The panel then says *Watching (periodic scans only)*.
- **Unplugged or offline folders** are checked again with growing intervals. Watching
  resumes on its own when the folder is back.
- **OneDrive files that are only in the cloud** wait until OneDrive downloads them.
  Mark the folder **Always keep on this device**; see
  [Xbox through OneDrive](./xbox-onedrive.md).

More technical detail: [watched-folder architecture](../architecture/watched-folders.md).
