-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0007: derived media (M08, contract 1.6).
--   * derived_artifacts holds one row per (asset, kind): the playback proxy, the
--     filmstrip thumbnails, or the waveform. The files live under
--     library/derived/<asset-id>/ and are replaceable; these rows say which file
--     is current and how it was made (recipe and cache key).
--   * status 'ready' points at a complete artifact; 'failed' means the artifact was
--     never produced. A failed regeneration keeps the previous artifact and records
--     last_error_json.
--   * Rows cascade with their asset. Deleting a row never deletes media; files
--     without a row are removed by the derived-media cleanup.

CREATE TABLE derived_artifacts (
    asset_id         TEXT NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    kind             TEXT NOT NULL CHECK (kind IN ('proxy', 'filmstrip', 'waveform')),
    status           TEXT NOT NULL CHECK (status IN ('ready', 'failed')),
    cache_key        TEXT NOT NULL CHECK (length(cache_key) = 64),
    recipe_json      TEXT NOT NULL,
    info_json        TEXT,
    relpath          TEXT CHECK (relpath IS NULL OR relpath GLOB 'derived/*'),
    size_bytes       INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    sha256           TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
    created_at       TEXT,
    last_error_json  TEXT,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (asset_id, kind),
    CHECK (status = 'failed' OR (relpath IS NOT NULL AND sha256 IS NOT NULL
                                 AND size_bytes IS NOT NULL AND created_at IS NOT NULL
                                 AND info_json IS NOT NULL))
);
