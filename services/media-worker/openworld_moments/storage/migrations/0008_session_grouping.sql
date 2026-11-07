-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0008: session grouping (M11, contract 1.7).
--   * jobs gain the 'group' kind (table rebuilt: CHECK constraints cannot be
--     altered; nothing references jobs).
--   * media_assets.container_created_at keeps the container's creation time as
--     probed, so capture time can be re-estimated from all signals later. Rows
--     whose estimate came from the container are backfilled from it.
--   * sessions record how they were grouped (grouping_json: algorithm, version,
--     settings, per-link evidence) and when they last changed.
--   * session_corrections is the audit log of user corrections (merge, split,
--     reorder, remove, confirm). A corrected or confirmed session is never touched
--     by automatic grouping. Rows outlive the sessions they mention (no FK).

CREATE TABLE jobs_new (
    id               TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind             TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                   'diagnostic', 'probe', 'relink', 'check_sources',
                                                   'fingerprint', 'group')),
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
                      correlation_id, created_at, started_at, finished_at, result_json, idempotency_key)
SELECT id, kind, state, params_json, attempt, progress_done, progress_total, message, error_json,
       correlation_id, created_at, started_at, finished_at, result_json, idempotency_key
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX jobs_state ON jobs (state);
CREATE INDEX jobs_created_at ON jobs (created_at);

ALTER TABLE media_assets ADD COLUMN container_created_at TEXT;
UPDATE media_assets SET container_created_at = captured_at
WHERE captured_at IS NOT NULL AND captured_at_basis_json = '["container_metadata"]';

ALTER TABLE sessions ADD COLUMN grouping_json TEXT;
ALTER TABLE sessions ADD COLUMN updated_at TEXT;

CREATE TABLE session_corrections (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('merge', 'split', 'reorder', 'remove', 'confirm')),
    session_ids_json TEXT NOT NULL,
    asset_ids_json  TEXT NOT NULL,
    detail_json     TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX session_corrections_created_at ON session_corrections (created_at);
