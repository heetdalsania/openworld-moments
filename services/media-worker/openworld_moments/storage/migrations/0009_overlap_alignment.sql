-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0009: overlap alignment (M12, contract 1.8).
--   * jobs gain the 'align' kind (table rebuilt: CHECK constraints cannot be
--     altered; nothing references jobs).
--   * asset_overlaps stores one alignment per ordered pair of clips (A then B):
--     where B starts inside A, the repeated duration, confidence, and evidence,
--     with the algorithm and version that produced it (another version is stale).
--     A user override lives in its own columns, so recomputation never replaces it.
--     Rows cascade with either asset; nothing here touches media.
--   * session_corrections gains the 'overlap' kind (a user's overlap override).

CREATE TABLE jobs_new (
    id               TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind             TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                   'diagnostic', 'probe', 'relink', 'check_sources',
                                                   'fingerprint', 'group', 'align')),
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

CREATE TABLE asset_overlaps (
    asset_a              TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    asset_b              TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    algorithm            TEXT NOT NULL CHECK (length(algorithm) BETWEEN 1 AND 64),
    version              INTEGER NOT NULL CHECK (version >= 1),
    -- 'pending': no automatic result yet (a row created by a user override).
    status               TEXT NOT NULL CHECK (status IN ('matched', 'weak', 'ambiguous', 'no_match',
                                                         'insufficient', 'pending')),
    offset_ms            INTEGER,
    overlap_ms           INTEGER CHECK (overlap_ms IS NULL OR overlap_ms >= 0),
    confidence           REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    evidence_json        TEXT NOT NULL,
    computed_at          TEXT NOT NULL,
    override_overlap_ms  INTEGER CHECK (override_overlap_ms IS NULL OR override_overlap_ms >= 0),
    overridden_at        TEXT,
    PRIMARY KEY (asset_a, asset_b),
    CHECK (asset_a <> asset_b),
    CHECK ((override_overlap_ms IS NULL) = (overridden_at IS NULL)),
    CHECK (status <> 'matched' OR (offset_ms IS NOT NULL AND overlap_ms IS NOT NULL
                                   AND confidence IS NOT NULL))
);
CREATE INDEX asset_overlaps_b ON asset_overlaps (asset_b);

CREATE TABLE session_corrections_new (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('merge', 'split', 'reorder', 'remove', 'confirm',
                                                  'overlap')),
    session_ids_json TEXT NOT NULL,
    asset_ids_json  TEXT NOT NULL,
    detail_json     TEXT,
    created_at      TEXT NOT NULL
);
INSERT INTO session_corrections_new (id, kind, session_ids_json, asset_ids_json, detail_json, created_at)
SELECT id, kind, session_ids_json, asset_ids_json, detail_json, created_at FROM session_corrections;
DROP TABLE session_corrections;
ALTER TABLE session_corrections_new RENAME TO session_corrections;
CREATE INDEX session_corrections_created_at ON session_corrections (created_at);
