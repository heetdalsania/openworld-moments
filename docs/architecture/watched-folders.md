# Watched folders

M07 imports finished video files from folders the user chose, without touching
those folders. The work is split between the two processes:

| Desktop host (Rust) | Worker (Python) |
|---|---|
| Watches folders: native events plus periodic scans | Stores folder settings and one record per file version |
| Waits until a file stops changing and can be read | Decides whether a reported file needs an import |
| Notices offline folders and retries them with backoff | Runs the import ([import](./import.md)), probe included |

Code:

- **Host:** `apps/desktop/src-tauri/src/watch/`, split into `service.rs` (the
  loop), `stabilizer.rs`, `fsprobe.rs`, `patterns.rs`, and `sink.rs`.
- **Worker:** `services/media-worker/openworld_moments/watched/`.
- **UI:** `apps/desktop/src/WatchedFolders.tsx` and `XboxOnboarding.tsx`.
- **Contract:** `watched-folder.schema.json` (contracts 1.5).
- **Migration:** 0006.

## Lifecycle of a file

1. **Something marks the file as possibly changed:**
   - a native OS event (create, modify, rename into the folder; a folder moved
     in is scanned);
   - a reconciliation scan;
   - the folder becoming available again.
2. **The host filters it:**
   - it must have a supported video extension;
   - it must match the folder's include and exclude patterns;
   - it must be inside the folder and not reached through a link;
   - it must not be in a subfolder of a non-recursive folder.
3. **The host waits for it to stabilize.** The host re-checks every pending file
   every second. The file counts as **stable** once its size and modification
   time have been unchanged for **10 seconds** and it can be opened for reading.
   Any change restarts the wait. Repeated events with no change do not.
4. **The host reports it** to the worker:
   `POST /v1/watched-folders/{id}/files` with
   `{relative_path, size_bytes, mtime_ns}`.
5. **The worker decides** (`WatchedFileDecision`):

   | Situation | Action |
   |---|---|
   | New path, or a new version (size or mtime changed) | `queued`: starts an `import` job with the folder's mode and source kind |
   | This version's import is queued or running | `in_progress` |
   | This version was imported, or failed for a reason retrying will not fix (e.g. `media.damaged`) | `known` |
   | This version failed for a retryable reason (`import.source_changed`, `import.disk_full`, cancellation, …) | `backoff` until `retry_at`, then a new attempt. Up to 5 attempts, waiting 1, 2, 4, 8 minutes |
   | Wrong extension or pattern | `ignored` |

6. **The import runs** as usual. It probes the file before anything is stored
   (the "successful probe" part of stabilization), and identical bytes resolve
   to the existing asset.

The import job's idempotency key is `watch:<folder>:<hash of path, size,
mtime>:<attempt>`. The same report sent twice, even concurrently, starts one
job. A file that is still being synced when it is probed fails with
`media.damaged`. When the sync finishes, its size and mtime change, so the new
version is imported.

## Defaults

| Setting | Default | Where |
|---|---|---|
| Stabilization period | 10 s unchanged size and mtime, plus a readable handle | `WatchConfig::stable_for` |
| Re-check of pending files | every 1 s | `WatchConfig::tick` |
| Reconciliation scan | at start, when a folder becomes available, then every 15 min | `WatchConfig::reconcile_every` |
| Folder list reload | every 60 s, and immediately after a change in the UI or a worker (re)start | `WatchConfig::reload_every` |
| Offline folder checks | after 15 s, then doubling, at most every 15 min | `WatchConfig::backoff_base` / `backoff_max` |
| Scan bounds | 100,000 files and 32 levels per folder | `WatchConfig::max_scan_entries` / `max_depth` |
| Import mode | `reference` | per folder |
| Subfolders | included | per folder |
| Exclude patterns | `.*` (hidden files), `**/.*/**` (anything inside a hidden folder) | per folder |
| Retryable import failures | 5 attempts, waiting 60 s × 2^(attempt−1), at most 1 h | `watched/service.py` |

## Patterns

Include and exclude are lists of up to 32 globs, matched case-insensitively
against the path relative to the folder, with `/` as the separator:

- **Which part they match:** a pattern without `/` matches the file name; a
  pattern with `/` matches the whole relative path.
- **Wildcards:** `*` and `?` stay within one path segment. `**` as a whole
  segment spans any number of segments (`Halo/**`, `**/raw/*.mp4`); inside a
  segment it acts like `*`.
- **Include:** an empty include list means every supported video file.
  Non-video files are never candidates, whatever include says.

The host (`patterns.rs`) and the worker (`patterns.py`) implement the same
rules and both run the shared cases in
`packages/contracts/fixtures/watched-folder/patterns.json`. The worker checks
patterns again on every report.

## Unavailable folders and cloud files

- **A folder that cannot be read** (unplugged drive, offline network share,
  deleted folder) moves to `unavailable`:
  - The host logs the change **once** and reports it **once** with
    `POST /v1/watched-folders/{id}/scans`
    (`{available: false, error: watch.folder_unavailable}`).
  - It drops the folder's watcher and pending files, and checks again only
    after the backoff delay.
  - No events, scans, reports, or jobs happen meanwhile.
- **When the folder comes back**, it is rescanned in full.
- **Cloud placeholders:** on Windows, files whose bytes are not on this
  computer (OneDrive Files On-Demand placeholders: the offline, recall-on-open,
  or recall-on-data-access attributes) are counted as "still in the cloud" and
  never opened, so the app does not trigger downloads. Once OneDrive downloads
  one, it is treated like any new file. The onboarding copy asks users to mark
  the captures folder *Always keep on this device*.

## Platform differences

The host uses the `notify` crate's recommended backend for each platform:

| Platform | Backend | Notes |
|---|---|---|
| Windows | `ReadDirectoryChangesW` | Placeholder detection applies here only |
| macOS | FSEvents | Events report canonical paths (for example `/private/var/...` for `/var/...`); the host matches both the configured and the canonical root |
| Linux | inotify | Large trees can hit the user's inotify watch limit |

- **No native events:** if they cannot be started for a folder (unsupported
  network filesystem, watch limits), the folder shows "Watching (periodic scans
  only)". New files are then found by the 15-minute reconciliation scan.
- **Events are only hints:** every candidate is re-checked by its metadata, so
  lost, duplicated, or coalesced events never cause a wrong or repeated import.
  Access events (open, read, read-only close) are dropped because they cannot
  change a file; on Linux the watcher's own scans would otherwise trigger new
  events. Each tick handles at most 10,000 distinct event paths, so an event
  storm cannot stall the loop.
- **Links are never followed** inside a watched folder, so a file is never
  reached through a symlink or junction.

## Safety

- **Read-only access:** the host only reads metadata, lists folders, and opens
  files read-only to test readability. The worker imports in reference mode by
  default, or copies in managed mode (M05). Nothing in a watched folder is ever
  written, moved, renamed, or deleted.
- **Removing a folder only stops watching:** `DELETE /v1/watched-folders/{id}`
  deletes its configuration and file records, never files.
- **Paths can't escape:** reported paths are relative and are checked by the
  worker. Absolute paths, drive prefixes, `..`, empty segments, and
  backslashes are refused (`watch.invalid_path`).
- **No paths in logs:** logs name folders by ID only.
- **Disabled folders do no work:** no watcher, no scans, no reports. Reports
  for a disabled folder are refused (`watch.folder_disabled`, 409).

## API (worker)

| Method | Path | Result |
|---|---|---|
| GET | `/v1/watched-folders` | `WatchedFolder[]`, with `stats` (tracked, imported, in progress, failed), `availability`, `last_scan_at`, `last_error` |
| POST | `/v1/watched-folders` | `WatchedFolderRequest` with `path`. 201, or 409 `watch.already_watched`, or 422 `watch.not_a_folder` |
| GET / PATCH / DELETE | `/v1/watched-folders/{id}` | Read, change (no `path`), stop watching (204) |
| POST | `/v1/watched-folders/{id}/files` | `WatchedFileReport` → `WatchedFileDecision` |
| GET | `/v1/watched-folders/{id}/files` | `WatchedFile[]`, latest first, with state derived from the import job |
| POST | `/v1/watched-folders/{id}/scans` | `ScanReport` → `WatchedFolder` |

The host exposes these to the UI as Tauri commands: `watched_folders_list`
(folders plus live host status), `watched_folder_add`, `watched_folder_update`,
`watched_folder_remove`, and `watched_folder_files`. The folder picker uses
`tauri-plugin-dialog` (`dialog:allow-open`).

## Xbox onboarding

The UI shows an optional "Import Xbox captures automatically" card when no Xbox
folder is watched (dismissible). It says plainly that the app does not connect
to Xbox or OneDrive, and walks through four steps:

1. Back up or upload captures to OneDrive from the console. The card links to
   [Xbox Support: Back up your game captures](https://support.xbox.com/en-US/help/games-apps/my-games-apps/back-up-game-clips).
2. Install OneDrive on the computer.
3. Mark the folder *Always keep on this device*.
4. Choose that folder.

The user guide is [Xbox captures through OneDrive](../guides/xbox-onedrive.md).

## Error codes

| Code | When |
|---|---|
| `watch.invalid_request` | Malformed folder or report body (422) |
| `watch.not_a_folder` | The path to watch is not a readable folder (422) |
| `watch.already_watched` | The folder is already watched (409) |
| `watch.folder_not_found` | Unknown folder ID (404) |
| `watch.folder_disabled` | A report for a disabled folder (409) |
| `watch.invalid_path` | A reported path that could leave the folder, or a subfolder of a non-recursive folder (422) |
| `watch.folder_unavailable` | Host report: the folder cannot be read (`last_error`, **retryable**) |

## macOS recovery (M35)

Native reauthorization accepts the same configured root without deleting folder/file records. Live status adds optional `unavailable_reason` (`permission-required`, `download-required`, `offline`, or other unavailability). `SF_DATALESS` files are counted without opening; dataless directories are not enumerated. Workspace sleep pauses watchers and resets pending stabilization; wake immediately reconciles configured roots while persistent idempotency prevents duplicate imports. See [macOS files and lifecycle](../platforms/macos-files-and-lifecycle.md).
