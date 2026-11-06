-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0004: safe import pipeline (M05, contract 1.3).
--   * jobs gain the 'relink' and 'check_sources' kinds and a unique, optional
--     idempotency_key. The CHECK constraint cannot be altered, so the table is
--     rebuilt (create, copy, drop, rename). Nothing references jobs.
--   * media_assets gain size_bytes (the source size at import, used to notice a
--     replaced file) and an index for listing missing assets.
--   * asset_imports records provenance: every place an asset's bytes were
--     imported from, once per (asset, path); repeating an import only updates
--     last_seen_at.

CREATE TABLE jobs_new (
    id               TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind             TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                   'diagnostic', 'probe', 'relink', 'check_sources')),
    state            TEXT NOT NULL CHECK (state IN ('queued', 'probing', 'fingerprinting', 'proxying', 'grouping',
                                                    'analyzing', 'transcribing', 'indexing', 'rendering', 'ready',
                                                    'cancelled', 'failed')),
    params_json      TEXT,
    attempt          INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    progress_done    INTEGER CHECK (progress_done >= 0),
    progress_total   INTEGER CHECK (progress_total >= 1),
    message          TEXT,
    error_json       TEXT,
    correlation_id   TEXT,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    result_json      TEXT,
    idempotency_key  TEXT UNIQUE CHECK (idempotency_key IS NULL OR length(idempotency_key) BETWEEN 1 AND 128),
    CHECK ((progress_done IS NULL) = (progress_total IS NULL)),
    CHECK (progress_done IS NULL OR progress_done <= progress_total),
    CHECK (state <> 'failed' OR error_json IS NOT NULL)
);

INSERT INTO jobs_new (id, kind, state, params_json, attempt, progress_done, progress_total, message, error_json,
                      correlation_id, created_at, started_at, finished_at, result_json)
SELECT id, kind, state, params_json, attempt, progress_done, progress_total, message, error_json,
       correlation_id, created_at, started_at, finished_at, result_json
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX jobs_state ON jobs (state);
CREATE INDEX jobs_created_at ON jobs (created_at);

ALTER TABLE media_assets ADD COLUMN size_bytes INTEGER CHECK (size_bytes >= 0);
CREATE INDEX media_assets_missing ON media_assets (missing_at) WHERE missing_at IS NOT NULL;

CREATE TABLE asset_imports (
    id             INTEGER PRIMARY KEY,
    asset_id       TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    import_mode    TEXT NOT NULL CHECK (import_mode IN ('reference', 'managed')),
    source_kind    TEXT NOT NULL CHECK (source_kind IN
                       ('xbox', 'playstation', 'obs', 'capture_card', 'phone_upload', 'other')),
    -- Absolute path the bytes were read from. Local data only; never logged.
    source_path    TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL CHECK (size_bytes >= 0),
    mtime_ns       INTEGER NOT NULL,
    -- The import or relink job that last saw this source (no FK: jobs may be pruned).
    job_id         TEXT CHECK (job_id IS NULL OR (job_id GLOB 'job_*' AND length(job_id) = 30)),
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    UNIQUE (asset_id, source_path)
);
CREATE INDEX asset_imports_source_path ON asset_imports (source_path);
