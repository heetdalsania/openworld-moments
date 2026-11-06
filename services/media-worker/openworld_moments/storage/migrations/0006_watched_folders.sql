-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0006: watched folders (M07, contract 1.5).
--   * watched_folders (from 0001) gains import mode, recursion, include/exclude
--     patterns, timestamps, and the availability last reported by the host.
--   * watched_files records the latest version (size, mtime) of each file seen
--     in a watched folder and the import job submitted for it, so repeated
--     events and restarts never import the same version twice. The state shown
--     to users is derived from that job. Deleting a folder's configuration
--     deletes these rows only; files on disk are never touched.

ALTER TABLE watched_folders ADD COLUMN mode TEXT NOT NULL DEFAULT 'reference'
    CHECK (mode IN ('reference', 'managed'));
ALTER TABLE watched_folders ADD COLUMN recursive INTEGER NOT NULL DEFAULT 1 CHECK (recursive IN (0, 1));
ALTER TABLE watched_folders ADD COLUMN include_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE watched_folders ADD COLUMN exclude_json TEXT NOT NULL DEFAULT '[".*","**/.*/**"]';
ALTER TABLE watched_folders ADD COLUMN updated_at TEXT;
UPDATE watched_folders SET updated_at = created_at;
ALTER TABLE watched_folders ADD COLUMN last_scan_at TEXT;
ALTER TABLE watched_folders ADD COLUMN availability TEXT NOT NULL DEFAULT 'unknown'
    CHECK (availability IN ('unknown', 'available', 'unavailable'));
ALTER TABLE watched_folders ADD COLUMN last_error_json TEXT;

CREATE TABLE watched_files (
    folder_id      INTEGER NOT NULL REFERENCES watched_folders (id) ON DELETE CASCADE,
    relative_path  TEXT NOT NULL CHECK (length(relative_path) BETWEEN 1 AND 4096),
    size_bytes     INTEGER NOT NULL CHECK (size_bytes >= 1),
    mtime_ns       INTEGER NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    -- The latest import job for this version (no FK: jobs may be pruned).
    job_id         TEXT CHECK (job_id IS NULL OR (job_id GLOB 'job_*' AND length(job_id) = 30)),
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (folder_id, relative_path)
);
CREATE INDEX watched_files_job ON watched_files (job_id);
