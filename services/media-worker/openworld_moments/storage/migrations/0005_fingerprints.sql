-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0005: fingerprints and duplicate candidates (M06, contract 1.4).
--   * jobs gain the 'fingerprint' kind (table rebuilt: CHECK constraints cannot
--     be altered; nothing references jobs).
--   * asset_fingerprints holds one versioned fingerprint per (asset, kind):
--     'fast' (partial hash), 'frames' (sampled perceptual hashes), 'audio'
--     (energy envelope). data_json is small canonical JSON, never media.
--   * duplicate_candidates records perceptual look-alikes for review. Rows never
--     cause deletion; review_state is set only by a person.

CREATE TABLE jobs_new (
    id               TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind             TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                   'diagnostic', 'probe', 'relink', 'check_sources',
                                                   'fingerprint')),
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

CREATE TABLE asset_fingerprints (
    asset_id     TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('fast', 'frames', 'audio')),
    algorithm    TEXT NOT NULL CHECK (length(algorithm) BETWEEN 1 AND 64),
    version      INTEGER NOT NULL CHECK (version >= 1),
    data_json    TEXT NOT NULL,
    computed_at  TEXT NOT NULL,
    PRIMARY KEY (asset_id, kind)
);

CREATE TABLE duplicate_candidates (
    id             INTEGER PRIMARY KEY,
    asset_a        TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    asset_b        TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('perceptual')),
    score          REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    evidence_json  TEXT NOT NULL,
    algorithm      TEXT NOT NULL,
    version        INTEGER NOT NULL CHECK (version >= 1),
    review_state   TEXT NOT NULL DEFAULT 'unreviewed'
                       CHECK (review_state IN ('unreviewed', 'duplicate', 'distinct')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    CHECK (asset_a < asset_b),
    UNIQUE (asset_a, asset_b, kind)
);
CREATE INDEX duplicate_candidates_asset_b ON duplicate_candidates (asset_b);
CREATE INDEX duplicate_candidates_review ON duplicate_candidates (review_state);

CREATE INDEX media_assets_duration ON media_assets (duration_ms);
