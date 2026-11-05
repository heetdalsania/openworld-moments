-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0003: jobs gain the 'probe' kind and a stored handler result; media assets
-- gain rotation and frame-rate detail (contract 1.2). The jobs CHECK constraint
-- cannot be altered, so that table is rebuilt; media_assets only gains columns.

CREATE TABLE jobs_new (
    id              TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind            TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render',
                                                  'diagnostic', 'probe')),
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
    result_json     TEXT,
    CHECK ((progress_done IS NULL) = (progress_total IS NULL)),
    CHECK (progress_done IS NULL OR progress_done <= progress_total),
    CHECK (state <> 'failed' OR error_json IS NOT NULL)
);

INSERT INTO jobs_new (id, kind, state, params_json, attempt, progress_done, progress_total, message, error_json,
                      correlation_id, created_at, started_at, finished_at)
SELECT id, kind, state, params_json, attempt, progress_done, progress_total, message, error_json,
       correlation_id, created_at, started_at, finished_at
FROM jobs;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX jobs_state ON jobs (state);
CREATE INDEX jobs_created_at ON jobs (created_at);

-- Clockwise display rotation of the coded frame.
ALTER TABLE media_assets ADD COLUMN rotation INTEGER CHECK (rotation IN (0, 90, 180, 270));
-- Container average frame rate, exact; both or neither.
ALTER TABLE media_assets ADD COLUMN avg_fps_num INTEGER CHECK (avg_fps_num > 0);
ALTER TABLE media_assets ADD COLUMN avg_fps_den INTEGER CHECK (avg_fps_den > 0);
ALTER TABLE media_assets ADD COLUMN variable_frame_rate INTEGER CHECK (variable_frame_rate IN (0, 1));
