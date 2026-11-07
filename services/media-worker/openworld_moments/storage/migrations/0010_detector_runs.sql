-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M14: detector provenance and independently restartable detector/asset results.
ALTER TABLE events ADD COLUMN tool_versions_json TEXT;
ALTER TABLE events ADD COLUMN input_key TEXT;

CREATE TABLE detector_runs (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    detector_id TEXT NOT NULL,
    cache_key TEXT NOT NULL CHECK (length(cache_key) = 64),
    event_ids_json TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (session_id, asset_id, detector_id)
);
