-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0002: jobs gain the 'diagnostic' kind, stored handler params, and an attempt
-- counter (contract Job 1.1). SQLite cannot alter a CHECK constraint, so the
-- table is rebuilt: create, copy, drop, rename. Nothing references jobs.

CREATE TABLE jobs_new (
    id              TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind            TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                  'diagnostic')),
    state           TEXT NOT NULL CHECK (state IN ('queued', 'probing', 'fingerprinting', 'proxying', 'grouping',
                                                   'analyzing', 'transcribing', 'indexing', 'rendering', 'ready',
                                                   'cancelled', 'failed')),
    params_json     TEXT,
    attempt         INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    progress_done   INTEGER CHECK (progress_done >= 0),
    progress_total  INTEGER CHECK (progress_total >= 1),
    message         TEXT,
    error_json      TEXT,
    correlation_id  TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    CHECK ((progress_done IS NULL) = (progress_total IS NULL)),
    CHECK (progress_done IS NULL OR progress_done <= progress_total),
    CHECK (state <> 'failed' OR error_json IS NOT NULL)
);

INSERT INTO jobs_new (id, kind, state, attempt, progress_done, progress_total, message, error_json,
                      correlation_id, created_at, started_at, finished_at)
SELECT id, kind, state, 1, progress_done, progress_total, message, error_json,
       correlation_id, created_at, started_at, finished_at
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX jobs_state ON jobs (state);
CREATE INDEX jobs_created_at ON jobs (created_at);
