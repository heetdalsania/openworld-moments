-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M20: bounded cancellable story jobs and immutable candidate snapshots.
CREATE TABLE jobs_new (
    id               TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind             TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                   'diagnostic', 'probe', 'relink', 'check_sources',
                                                   'fingerprint', 'group', 'align', 'story')),
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

CREATE TABLE story_candidates (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    settings_key TEXT NOT NULL,
    input_key TEXT NOT NULL,
    layout_key TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX story_candidates_session ON story_candidates(session_id, settings_key, input_key);
CREATE TABLE story_decisions (
    candidate_id TEXT NOT NULL REFERENCES story_candidates(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision > 0),
    state TEXT NOT NULL CHECK(state IN ('suggested','accepted','rejected')),
    input_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id,revision)
);
CREATE TABLE story_generations (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    settings_key TEXT NOT NULL,
    input_key TEXT NOT NULL,
    candidate_count INTEGER NOT NULL CHECK(candidate_count >= 0),
    computed_at TEXT NOT NULL,
    PRIMARY KEY(session_id,settings_key)
);
