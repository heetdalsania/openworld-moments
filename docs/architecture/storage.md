# Storage

Implemented in M02 (`services/media-worker/openworld_moments/storage/`).
Decision record: [ADR-0003](./adr/0003-sqlite-migrations.md).

## What lives where

| Kind of state | Where | Why |
|---|---|---|
| Asset identity and metadata, sessions, session membership, events, transcripts, stories (with their EDL), render jobs, jobs, tags, collections, watched folders, settings | `library/database.sqlite3` (SQLite, WAL) | Canonical, queryable, transactional |
| Original footage | Where the user keeps it (reference mode) or `library/managed-media/ab/cd/<sha256>.<ext>` (managed mode) | Never modified; the database stores paths and hashes only |
| Proxies, waveforms, thumbnails, sampled frames | `library/derived/<asset-id>/` (macOS M35: Caches root) | Large and replaceable; can always be regenerated |
| Exported videos and manifests | `library/exports/` | User output |
| Database backups | `library/backups/` | Written before every upgrade of a non-empty database |
| Models, profiles, logs | `library/models/`, `library/profiles/`, `library/logs/` | Managed by their own milestones |

Rules:

- Binary data never goes into SQLite. Rows reference files by path or hash.
  Fingerprints are small JSON metadata (a few KB per asset), not media.
- Anything under `derived/` may be deleted at any time; the database must not
  depend on it existing. A deleted derived file shows as `missing` and is
  rebuilt from the asset ([derived media](./derived-media.md)).
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
| `AssetRepository` | `media_assets` | contract `MediaAsset` (+ `original_path`, `managed_path`, `source_profile_id` kept out of the contract for privacy). Since 0008 also `container_created_at` (the probed container time, for re-estimating capture time). Since 0003 also `rotation`, `average_frame_rate`, and `variable_frame_rate`; added color fields live in `color_metadata_json`. Since 0004 `size_bytes`, since 0005 `set_fast_hash`, `ids_by_fast_hash`, `ids_with_duration`, plus `query(missing=)`, `location(s)` (paths for the missing-source check), `set_original_path`, `clear_missing`. `managed_path` is relative to the library (`managed-media/ab/cd/<sha256>.<ext>`) |
| `FingerprintRepository` | `asset_fingerprints` (0005) | One versioned fingerprint per (asset, kind): `fast`, `frames`, `audio`; small canonical JSON, never media. Cascades with its asset ([fingerprints](./fingerprints.md)) |
| `DuplicateCandidateRepository` | `duplicate_candidates` (0005) | Perceptual look-alike pairs (`asset_a < asset_b`). Re-recording refreshes score and evidence but never `review_state`. Cascades with either asset; never deletes media |
| `DerivedArtifactRepository` | `derived_artifacts` (0007) | One row per (asset, kind) for the proxy, filmstrip, and waveform: status (`ready` or `failed`), cache key, recipe, kind-specific info, the artifact's logical path (`derived/<asset-id>/…`, resolved under the configured derived-media root), size, digest, and the last error. A failed regeneration keeps the previous ready artifact. Cascades with the asset; rows never delete files ([derived media](./derived-media.md)) |
| `WatchedFolderRepository` | `watched_folders` (0001, extended in 0006), `watched_files` (0006) | Folder settings (mode, recursion, include/exclude, availability, last scan) and the latest version (size, mtime) of each file with its import job. Deleting a folder deletes only these rows ([watched folders](./watched-folders.md)) |
| `AssetImportRepository` | `asset_imports` (0004) | Import provenance: one row per (asset, source path), upserted on re-import (`last_seen_at`); cascades with its asset |
| `SessionRepository` | `sessions`, `session_assets`, `session_corrections` (0008) | `Session` (since 0008 with `grouping` evidence and `updated_at`), `SessionAsset`; `update`, `replace_assets`, `newest`, `session_of`, `has_stories`, `has_attached_data` / `with_attached_data`, and the correction log (`log_correction`, `corrections`). Rows never delete media ([sessions](./sessions.md)) |
| `OverlapRepository` | `asset_overlaps` (0009) | One alignment per ordered clip pair (status, offset, overlap, confidence, evidence, algorithm version) plus a separate user override; `effective` returns what timelines apply. Cascades with either asset ([overlap](./overlap.md)) |
| search (M26) | `search_documents`, `search_fts`, `search_index_state`, `collections`, `collection_items` | Migration 0016: derived search documents maintained by triggers from `search_source_*` views, an external-content FTS5 index with secure-delete, index state, and reshaped collections (manual items referencing exactly one clip, session, event, transcript span or project; rule collections store a JSON rule). Search data is rebuildable and clearable without touching canonical rows ([search](./search.md)). |
| renders (M24) | `render_jobs` | Migration 0015 adds project revision, encoder, plan, validation, output (library-relative), CPU fallback and finish time. A row is `ready` only after validation passed and the files moved into `renders/<project>/` ([render engine](./render.md)). |
| transcripts (M18) | `transcript_segments`, `transcript_runs` | Migration 0011 adds `asset_id`, source times, `transcriber_json` and `created_at` to segments, and per-clip `transcript_runs` cache rows. Rows from before M18 are kept but not listed. Deleting a transcript removes only these rows ([transcription](./transcription.md)). |
| `EventRepository` | `events` | contract `Event`; migration 0010 adds detector `tool_versions_json` and `input_key`. `page_for_session` bounds API reads. `detector_runs` caches one successful result per session/asset/detector, atomically with its events ([detectors](./detectors.md)). |
| `JobRepository` | `jobs` | contract `Job` (including `params` and `attempt` since migration 0002, `result` since 0003, `idempotency_key` since 0004 with `find_by_idempotency_key`) |
| `StoryRepository` | `stories` | `Story`, whose `timeline` is a contract `Project` with the same ID |
| `SettingsRepository` | `settings` | JSON values |

Rows read back are validated through the contracts' `load()`, so storage
cannot return a document that breaks its contract. Errors: `NotFoundError`,
`ConflictError` (uniqueness or reference), and `InUseError` (delete refused).

`transcript_segments`, `render_jobs`, `tags`, `collections`, and
`collection_items` have tables and constraints now; their repositories arrive
with the milestones that use them (M18, M24, M26).

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
- Several processes may open the same library at once (for example the CLI
  during app start): the version and the ledger are read in one read
  transaction (one consistent snapshot), each migration re-checks the version
  under the write lock and skips work another process finished, and the switch
  to WAL retries while locked.

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

M19 migration `0012_event_review.sql` adds immutable `event_observations` and append-only `event_decisions`. Archived observations count as attached session data. See [event review](./event-review.md).

M20 migration `0013_story_candidates.sql` adds immutable candidates, append-only decisions, generation cache markers and the `story` job kind. Existing Story/Project rows are created only on explicit acceptance. See [story engine](./stories.md).

M21 migration `0014_editor_projects.sql` adds current and previous committed editor documents with revision checks. Story EDL and autosave update atomically; legacy stories remain readable and migrate on editor open. See [editor projects](./editor-projects.md).

M27 migration `0017_render_manifests.sql` adds `render_jobs.manifest_json`, the canonical export manifest of each completed render, so re-exporting it is byte-stable even without the sidecar file. See [exports](./exports.md).

M26 migration `0016_search_and_collections.sql` adds the derived search index (documents, source views, maintenance triggers, FTS5 with secure-delete, index state) and builds it for the existing library. It reshapes the unused 0001 `collections`/`collection_items` tables: collection IDs become `col_` IDs (existing rows keep a zero-padded form of their number), collections are `manual` or `rule`, and items may reference clips and transcript spans. Requires SQLite 3.42+ (FTS5 secure-delete). See [search](./search.md).

## M28 privacy review

See [privacy and spoiler review](./privacy-review.md) for the mandatory current-review
gate on project exports and new renders, contracts 1.22, output-space moving blur
keyframes, local hashed decisions and explicit text-only deletion. Caption-panel
sidecars now flush the project and use the gated `project_export` host command;
`caption_export` is removed. Render engine 1.2.0 uses end-exclusive privacy blurs.
Migration 0018 stores review configuration/decisions without copied evidence text.

## macOS storage (M35)

The host now uses standard Caches/Logs/temp paths for replaceable media, redacted rotating logs and phone staging. Native selection remembers an existing relocated library; an offline selection never creates an empty database. Atomic import/render finalization staging stays on the canonical library volume. See [paths and lifecycle](../platforms/macos-files-and-lifecycle.md).
