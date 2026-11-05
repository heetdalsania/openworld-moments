# Storage

Implemented in M02 (`services/media-worker/openworld_moments/storage/`).
Decision record: [ADR-0003](./adr/0003-sqlite-migrations.md).

## What lives where

| Kind of state | Where | Why |
|---|---|---|
| Asset identity and metadata, sessions, session membership, events, transcripts, stories (with their EDL), render jobs, jobs, tags, collections, watched folders, settings | `library/database.sqlite3` (SQLite, WAL) | Canonical, queryable, transactional |
| Original footage | Where the user keeps it (reference mode) or `library/managed-media/ab/cd/<sha256>.<ext>` (managed mode) | Never modified; the database stores paths and hashes only |
| Proxies, waveforms, thumbnails, sampled frames | `library/derived/<asset-id>/` | Large and replaceable; can always be regenerated |
| Exported videos and manifests | `library/exports/` | User output |
| Database backups | `library/backups/` | Written before every upgrade of a non-empty database |
| Models, profiles, logs | `library/models/`, `library/profiles/`, `library/logs/` | Managed by their own milestones |

Rules:

- Binary data never goes into SQLite. Rows reference files by path or hash.
- Anything under `derived/` may be deleted at any time; the database must not
  depend on it existing.
- Settings hold small JSON values only, never secrets or footage.
- Support bundles may include `DatabaseHealth`, which contains no paths or user
  data (spec §14.3).

## Connections and transactions

- `Database.open(path)` creates the file if needed and migrates it to head.
- `database.connect()` returns a connection with `journal_mode=WAL`,
  `foreign_keys=ON`, `busy_timeout=5000`, and `synchronous=NORMAL`.
- Group writes with `with transaction(conn): ...` (`BEGIN IMMEDIATE`).
  Repositories never commit on their own.
- Expect one writer at a time. In WAL mode, readers keep reading the last
  committed state while it writes.

## Repositories

| Repository | Table(s) | Types |
|---|---|---|
| `AssetRepository` | `media_assets` | contract `MediaAsset` (+ `original_path`, `managed_path`, `source_profile_id` kept out of the contract for privacy) |
| `SessionRepository` | `sessions`, `session_assets` | `Session`, `SessionAsset` |
| `EventRepository` | `events` | contract `Event` |
| `JobRepository` | `jobs` | contract `Job` |
| `StoryRepository` | `stories` | `Story`, whose `timeline` is a contract `Project` with the same ID |
| `SettingsRepository` | `settings` | JSON values |

Rows read back are validated through the contracts' `load()`, so storage
cannot return a document that breaks its contract. Errors: `NotFoundError`,
`ConflictError` (uniqueness or reference), and `InUseError` (delete refused).

`transcript_segments`, `render_jobs`, `tags`, `collections`,
`collection_items`, and `watched_folders` have tables and constraints now;
their repositories arrive with the milestones that use them (M07, M18, M24, M26).

## Delete policies

| When you delete... | Effect |
|---|---|
| a media asset still in a session or referenced by an event | **Refused** (`InUseError`). Remove it from the session first. Missing files are marked with `missing_at`, not deleted. |
| a session | Its `session_assets`, `events`, `transcript_segments`, and collection items are deleted with it. Source assets are untouched. |
| a session that has stories | **Refused** (`InUseError`). Stories are user work and are never dropped implicitly. |
| a story | Its `render_jobs` and collection items are deleted with it. |
| a collection | Its items are deleted with it. |

## Migrations

- Files: `openworld_moments/storage/migrations/NNNN_name.sql`, forward-only,
  numbered 1..n without gaps. **Never edit an applied migration**; a checksum
  check refuses to start if one changes. Add a new file instead.
- Each migration runs in its own transaction and is recorded in
  `schema_migrations`; `PRAGMA user_version` holds the current version.
- Every migration needs a data fixture
  `tests/storage/fixtures/data_vNNNN.sql` (rows valid at that version). Tests
  load each fixture at its version and upgrade it to head.
- A database newer than the app is refused with "update the app".

### Backups and recovery

- Before upgrading a database at version ≥ 1, a consistent copy is written to
  `<library>/backups/database-<UTC timestamp>-v<from>.sqlite3`.
- If a migration fails, it rolls back, the database stays at the last good
  version, and `MigrationError.backup_path` names the copy.
  `Database.restore(backup_path)` copies it back.
- Backups are not pruned yet; retention is a follow-up for M29/M31.

### Commands

```bash
cd services/media-worker
uv run python -m openworld_moments.storage status  <library>/database.sqlite3
uv run python -m openworld_moments.storage migrate <library>/database.sqlite3
uv run python -m openworld_moments.storage backup  <library>/database.sqlite3
```

Output is JSON. Exit code 0 means healthy or done, 1 means unhealthy or failed.
