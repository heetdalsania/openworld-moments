-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M18: local transcripts with their source clip, source times and transcriber
-- provenance, plus per-clip restartable transcription runs. Rows written before M18
-- (no transcriber) are kept untouched; the transcript API lists only M18 rows.
ALTER TABLE transcript_segments ADD COLUMN asset_id TEXT REFERENCES media_assets (id) ON DELETE CASCADE;
ALTER TABLE transcript_segments ADD COLUMN source_start_ms INTEGER CHECK (source_start_ms >= 0);
ALTER TABLE transcript_segments ADD COLUMN source_end_ms INTEGER CHECK (source_end_ms >= source_start_ms);
ALTER TABLE transcript_segments ADD COLUMN transcriber_json TEXT;
ALTER TABLE transcript_segments ADD COLUMN created_at TEXT;
CREATE INDEX transcript_segments_asset ON transcript_segments (session_id, asset_id);

CREATE TABLE transcript_runs (
    session_id    TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    asset_id      TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    cache_key     TEXT NOT NULL CHECK (length(cache_key) = 64),
    language      TEXT,
    segment_count INTEGER NOT NULL CHECK (segment_count >= 0),
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (session_id, asset_id)
);
