# Safe import pipeline

M05 adds media to the library in two modes, through a staging boundary, gated by
the M04 probe. Code: `services/media-worker/openworld_moments/ingest/`:

- `scan.py`: turns request paths into candidate files.
- `files.py`: streaming hash, staged copy, and atomic promotion.
- `library.py`: on-disk layout and staging cleanup.
- `importer.py`: batches, relink, and the missing-source check.

Contracts: `import.schema.json` (`ImportResult`, plus `$defs` `ImportRequest`,
`RelinkRequest`, `RelinkResult`, `SourceCheckResult`), and the job kinds
`import`, `relink`, and `check_sources` (contracts 1.3).

## Modes

| Mode | What happens | The source |
|---|---|---|
| `reference` | The database points at the file where it is | Opened read-only to probe and hash. Never moved, renamed, or written. Tests compare SHA-256, size, and `mtime_ns` before and after |
| `managed` | A copy goes into `library/managed-media/ab/cd/<sha256>.<ext>` | The same read-only access. The original is untouched |

Moving files is not offered (spec 8.1.3).

## API

All endpoints use the worker's loopback and token rules ([worker](./worker.md)).

| Method | Path | Body → result |
|---|---|---|
| POST | `/v1/imports` | `ImportRequest` + optional `idempotency_key` → 201 `Job` (kind `import`), or 200 with the earlier job for the same key |
| GET | `/v1/imports/{id}` | `Job`, whose `result` is the `ImportResult` (404 if the job is not an import) |
| GET | `/v1/assets?missing=bool&limit=N&offset=N` | `MediaAsset[]`, oldest first. `missing=true` lists assets whose source is gone |
| GET | `/v1/assets/{id}` | `MediaAsset` |
| POST | `/v1/assets/{id}/relink` | `{path, idempotency_key?}` → 201 `Job` (kind `relink`) |
| POST | `/v1/assets/check-sources` | → 201 `Job` (kind `check_sources`) |

`ImportRequest`:

```json
{"paths": ["/abs/folder", "/abs/clip.mp4"], "mode": "managed", "recursive": true, "source_kind": "xbox"}
```

- `paths`: 1 to 100 absolute paths. Each one is a file or a folder.
- `recursive` (default `false`): also scan subfolders.
- `source_kind` (default `other`): `xbox`, `playstation`, `obs`, `capture_card`, `phone_upload`, or `other`.
- Bad input is refused at submit time with 422 `job.invalid_params`.

`MediaAsset` never contains paths (privacy). Paths stay in the database and
in the job params, and are never logged.

## What gets imported

Scanning rules (`scan.py`):

- **A path you name is used as given**, even if it is a link: you chose it.
  A named file must have a video extension, or it fails with
  `import.not_media_extension`.
- **Video extensions:** `.mp4 .m4v .mov .mkv .webm .ts .m2ts .mts .avi .flv .3gp`,
  case-insensitive. Other files in a folder are reported as `skipped`.
- **Nothing inside a selected folder can lead outside it:**
  - Linked folders (symlinks, Windows junctions) are never followed:
    `import.linked_folder`.
  - A linked file is used only if its real target is inside the selected
    folder (`import.outside_root` otherwise). The target is opened, not the
    link, so the link cannot be swapped afterwards.
  - Every subfolder is also resolved and checked to be inside the selected
    folder.
  - Broken links: `import.broken_link`.
  - Devices, pipes, and sockets: `media.not_a_file`.
- **A file reached twice in one request is reported once**, for example through
  overlapping folders or a link plus its target.
- **Limits:** at most 10,000 reported files per import, or the job fails with
  `import.too_many_files` before importing anything. At most 32 folder levels
  (`import.too_deep`). At most 1 TiB per file (`import.file_too_large`).

## Per-file pipeline

Every candidate goes through these steps in order. The first failure becomes
that file's error, and the batch continues.

1. **Pre-check:** the file must be regular, non-empty, readable, and within the
   size limit. This takes a stat snapshot (size and `mtime_ns`).
2. **Probe** with FFprobe (M04). Anything that is not usable video stops here
   with the probe's error code (`media.damaged`, `media.no_video_stream`, …).
   Unsupported media never reaches managed storage or the database.
3. **Hash.** Reference mode streams the file to compute its SHA-256. Managed
   mode computes it while copying into staging: the copy is flushed and
   fsynced, and its byte count is checked on disk.
   - **Stability check:** size and `mtime_ns` must match the snapshot from
     step 1, and the bytes read must equal that size. Otherwise the file is
     still being written (for example by a sync client) and fails with
     `import.source_changed` (retryable).
4. **Promote** (managed only): the staged copy is renamed atomically to
   `managed-media/ab/cd/<sha256><ext>`. If a copy is already there, the staged
   copy is discarded.
5. **Commit:** one transaction writes the asset row, or finds the existing
   asset with the same SHA-256, plus a provenance row.

### Outcomes

| `outcome` | Meaning |
|---|---|
| `imported` | New asset |
| `existing` | The same bytes are already in the library (any path, either mode). No new row |
| `relinked` | The same bytes match an asset marked missing, and this import restored it. A reference import re-points a reference asset; a managed import re-copies a lost managed file |
| `skipped` | Not attempted: not a media file, or a link that leaves the selected folder |
| `failed` | Attempted and refused; `error` explains why |

Every candidate appears in `items`, and failures are never dropped. `totals` must
match `items`, which is checked semantically by the contract.

### Job result

| Batch | Job state | Error |
|---|---|---|
| At least one file `imported`, `existing`, or `relinked` | `ready` | None. Per-file failures are in the result |
| No media found (empty folder, or only skipped files) | `failed` | `import.no_media_found` |
| Every candidate failed: one file | `failed` | That file's own error (for example `media.damaged`) |
| Every candidate failed: several files | `failed` | `import.all_failed` (retryable if any file's error is) |

A failed import still stores its `ImportResult` as `result`, so every file's
reason stays visible. The final job `message` is a summary such as
"2 imported, 1 already in the library, 1 failed"; it never contains file names.

## Atomicity and interruption

- **No partial library files.** Copies are written under
  `library/staging/imports/<job-id>/` and enter `managed-media/` only through
  `os.replace` on the same volume. Readers see either no file or the complete,
  verified file. On POSIX the directory is fsynced after the rename.
- **Promotion happens before the row exists**, so an asset row never names a
  managed file that is missing. A crash between promotion and commit leaves
  only a complete, unreferenced copy. The next import of the same bytes adopts
  it.
- **Staging cleanup:**
  - On failure or cancellation, the staging file is removed immediately.
  - At the start and end of each import job, its staging folder is removed.
  - At worker start, all of `staging/imports/` is removed (no import runs yet).
- **Crash recovery:** imports are idempotent, so an interrupted `import`,
  `relink`, or `check_sources` job is requeued, up to 3 attempts
  ([worker rules](./worker.md#retry-and-crash-recovery-rules)). Files that
  finished before the crash resolve as `existing`.
- **Cancellation** is checked between files and between 1 MiB chunks. Files
  already committed stay imported. The job ends `cancelled`, without a result.
- **A full disk** (`ENOSPC` or `EDQUOT`) fails the file with `import.disk_full`
  (retryable). Before copying, a free-space check requires the file size plus
  256 MiB. Other write errors are `import.write_failed`.

## Idempotency

- **Per request:** submit the same `idempotency_key` again (for example after a
  UI retry or a lost response) and you get the original job with HTTP 200.
  Reusing the key for a different kind or different params returns 409
  `job.idempotency_conflict`. Keys are 1–128 characters from
  `[A-Za-z0-9._:-]`, stored in `jobs.idempotency_key`, which is unique.
  `POST /v1/jobs` accepts the same field.
- **Per content:** identical bytes always resolve to one asset, because
  `media_assets.sha256` is unique. Repeating an import updates only the
  provenance row's `last_seen_at` and creates no duplicate rows.

## Provenance

The `asset_imports` table has one row per (asset, source path), recording mode,
source kind, size, `mtime_ns`, the last job, and when the path was first and
last seen. A renamed copy of the same file adds a provenance row, not an asset.
`media_assets.original_path` keeps the path of the first import; relink and
re-import of a missing asset update it. `managed_path` is stored relative to
the library (`managed-media/ab/cd/…`), so the library folder can be moved.

Each asset also gets `size_bytes` (contract 1.3) and a preliminary
`capture_time`:

- From the container's `creation_time`: basis `container_metadata`, confidence 0.6.
- Otherwise from the file's mtime: basis `filesystem_mtime`, confidence 0.2.

Session grouping (M11) refines it.

## Missing sources and relink

- **`check_sources`** stats every asset's bytes: `original_path` for reference
  assets, the managed copy for managed ones.
  - A file that is gone, is no longer a regular file, or has a different size
    (it was replaced) gets `missing_at` set.
  - A file that comes back has the mark cleared.
  - The result counts `checked`, `missing`, `newly_missing`, and `restored`,
    and lists up to 1,000 `missing_asset_ids`.
- **`relink`** points a reference asset at a new path, only after
  `verify_identity` confirms the file is the same content: the size, then the
  full SHA-256. If they differ, the job fails with `relink.identity_mismatch`
  and the asset is unchanged. On success, `missing_at` is cleared, the path is
  updated, and a provenance row is added. The result is
  `{asset_id, verified_by: "sha256"}`.
- **Managed assets** are not relinked (`relink.not_referenced`). Importing the
  same file again in managed mode restores a lost library copy.

### Identity limitation (until M06)

Identity is the full SHA-256. That is exact, but it means:

- Every import reads every byte, and a managed import of something already in
  the library still copies it to staging before the duplicate is noticed.
- Relink always reads the whole candidate file.
- The missing-source check only compares sizes. A same-size in-place edit is
  not detected until the file is hashed again.

M06 adds the fast partial hash (early duplicate screening before copying, and
a cheap relink pre-check in `verify_identity`), perceptual fingerprints,
fingerprint versioning, and a backfill job. The SHA-256 computed here is the
exact identity M06 builds on.

## Error codes

Import-specific codes (probe codes such as `media.damaged` are listed in
[media](./media.md#stable-error-codes)):

| Code | When |
|---|---|
| `import.not_media_extension` | Not a supported video file type (failed if named directly, skipped in a folder) |
| `import.outside_root` | A link or folder that leads outside the selected folder (skipped) |
| `import.linked_folder` | A linked folder: never followed (skipped) |
| `import.broken_link` | A link to nothing readable (skipped) |
| `import.too_deep` | A folder more than 32 levels down (skipped) |
| `import.too_many_files` | More than 10,000 files in one import (job fails, nothing imported) |
| `import.file_too_large` | Over 1 TiB |
| `import.source_changed` | The file changed while it was read (**retryable**) |
| `import.disk_full` | Not enough space in the library (**retryable**) |
| `import.write_failed` | Another error writing the library copy (**retryable**) |
| `import.no_media_found` | The request contained no candidate files (job error) |
| `import.all_failed` | Every candidate failed (job error) |
| `relink.identity_mismatch` | The relink target's size or content differs |
| `relink.not_referenced` | Relink was requested for a managed asset |
| `asset.not_found` | Unknown asset ID |
| `job.idempotency_conflict` | The idempotency key was used for a different request (HTTP 409) |
| `job.invalid_idempotency_key` | The key has the wrong format (HTTP 422) |
