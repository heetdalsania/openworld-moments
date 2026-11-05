-- SPDX-License-Identifier: AGPL-3.0-or-later
-- 0001: initial schema for every core table in spec section 9.7.
--
-- Conventions
--   * IDs are contract IDs: '<prefix>_' + 26-char ULID (length 30), checked below.
--   * Timestamps are contract UtcTimestamp strings (RFC 3339, UTC, 'Z').
--   * Timeline values are integer milliseconds.
--   * *_json columns hold canonical JSON produced by the repository layer.
--
-- Delete policies (see docs/architecture/storage.md)
--   * media_assets are never removed out from under a session or event: RESTRICT.
--     Missing files are marked with missing_at instead of being deleted.
--   * Derived rows (session membership, events, transcripts, render jobs) CASCADE
--     with their parent session or story.
--   * stories RESTRICT session deletion: user edits are never dropped implicitly.

CREATE TABLE media_assets (
    id                      TEXT PRIMARY KEY CHECK (id GLOB 'ast_*' AND length(id) = 30),
    sha256                  TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    fast_hash               TEXT,
    original_name           TEXT NOT NULL,
    original_path           TEXT,
    managed_path            TEXT,
    source_kind             TEXT NOT NULL CHECK (source_kind IN
                                ('xbox', 'playstation', 'obs', 'capture_card', 'phone_upload', 'other')),
    import_mode             TEXT NOT NULL CHECK (import_mode IN ('reference', 'managed')),
    source_profile_id       TEXT,
    captured_at             TEXT,
    captured_at_confidence  REAL CHECK (captured_at_confidence BETWEEN 0 AND 1),
    captured_at_basis_json  TEXT,
    duration_ms             INTEGER NOT NULL CHECK (duration_ms >= 0),
    container               TEXT NOT NULL,
    width                   INTEGER CHECK (width > 0),
    height                  INTEGER CHECK (height > 0),
    fps_num                 INTEGER CHECK (fps_num > 0),
    fps_den                 INTEGER CHECK (fps_den > 0),
    video_codec             TEXT,
    pixel_format            TEXT,
    color_metadata_json     TEXT,
    audio_streams_json      TEXT,
    audio_codec             TEXT,
    created_at              TEXT NOT NULL,
    missing_at              TEXT,
    -- A capture time estimate is all-or-nothing.
    CHECK ((captured_at IS NULL) = (captured_at_confidence IS NULL)
       AND (captured_at IS NULL) = (captured_at_basis_json IS NULL)),
    -- Video stream columns are all-or-nothing.
    CHECK ((video_codec IS NULL) = (width IS NULL)
       AND (video_codec IS NULL) = (height IS NULL)
       AND (video_codec IS NULL) = (fps_num IS NULL)
       AND (video_codec IS NULL) = (fps_den IS NULL)
       AND (video_codec IS NULL) = (color_metadata_json IS NULL))
);
CREATE INDEX media_assets_fast_hash ON media_assets (fast_hash);
CREATE INDEX media_assets_captured_at ON media_assets (captured_at);

CREATE TABLE sessions (
    id                   TEXT PRIMARY KEY CHECK (id GLOB 'ses_*' AND length(id) = 30),
    title                TEXT NOT NULL,
    started_at           TEXT,
    ended_at             TEXT,
    source_profile_id    TEXT,
    game_profile_id      TEXT,
    grouping_confidence  REAL CHECK (grouping_confidence BETWEEN 0 AND 1),
    review_state         TEXT NOT NULL CHECK (review_state IN ('unreviewed', 'confirmed', 'corrected')),
    created_at           TEXT NOT NULL
);
CREATE INDEX sessions_started_at ON sessions (started_at);

CREATE TABLE session_assets (
    session_id                TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    asset_id                  TEXT NOT NULL REFERENCES media_assets (id) ON DELETE RESTRICT,
    order_index               INTEGER NOT NULL CHECK (order_index >= 0),
    session_start_ms          INTEGER NOT NULL CHECK (session_start_ms >= 0),
    trim_in_ms                INTEGER NOT NULL DEFAULT 0 CHECK (trim_in_ms >= 0),
    trim_out_ms               INTEGER CHECK (trim_out_ms IS NULL OR trim_out_ms > trim_in_ms),
    overlap_with_previous_ms  INTEGER NOT NULL DEFAULT 0 CHECK (overlap_with_previous_ms >= 0),
    alignment_confidence      REAL CHECK (alignment_confidence BETWEEN 0 AND 1),
    PRIMARY KEY (session_id, asset_id),
    UNIQUE (session_id, order_index)
);
CREATE INDEX session_assets_asset ON session_assets (asset_id);

CREATE TABLE events (
    id                      TEXT PRIMARY KEY CHECK (id GLOB 'evt_*' AND length(id) = 30),
    session_id              TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    asset_id                TEXT REFERENCES media_assets (id) ON DELETE RESTRICT,
    type                    TEXT NOT NULL,
    start_ms                INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms                  INTEGER NOT NULL CHECK (end_ms >= start_ms),
    confidence              REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    attributes_json         TEXT NOT NULL,
    evidence_json           TEXT NOT NULL,
    source_kind             TEXT NOT NULL CHECK (source_kind IN ('detector', 'model', 'user')),
    detector_id             TEXT,
    detector_version        TEXT,
    profile_id              TEXT,
    profile_version         TEXT,
    model_id                TEXT,
    prompt_version          TEXT,
    sampled_frames_json     TEXT,
    review_state            TEXT NOT NULL CHECK (review_state IN ('unreviewed', 'confirmed', 'corrected', 'rejected')),
    -- Source columns must match the source kind (observation vs suggestion).
    CHECK (source_kind <> 'detector' OR (detector_id IS NOT NULL AND detector_version IS NOT NULL
                                         AND model_id IS NULL AND prompt_version IS NULL AND sampled_frames_json IS NULL)),
    CHECK (source_kind <> 'model' OR (model_id IS NOT NULL AND prompt_version IS NOT NULL AND sampled_frames_json IS NOT NULL
                                      AND detector_id IS NULL AND detector_version IS NULL
                                      AND profile_id IS NULL AND profile_version IS NULL)),
    CHECK (source_kind <> 'user' OR (detector_id IS NULL AND detector_version IS NULL AND profile_id IS NULL
                                     AND profile_version IS NULL AND model_id IS NULL AND prompt_version IS NULL
                                     AND sampled_frames_json IS NULL))
);
CREATE INDEX events_session_time ON events (session_id, start_ms);
CREATE INDEX events_type ON events (type);
CREATE INDEX events_asset ON events (asset_id);

CREATE TABLE transcript_segments (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    start_ms    INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms      INTEGER NOT NULL CHECK (end_ms >= start_ms),
    speaker     TEXT,
    text        TEXT NOT NULL,
    language    TEXT,
    confidence  REAL CHECK (confidence BETWEEN 0 AND 1),
    words_json  TEXT
);
CREATE INDEX transcript_segments_session_time ON transcript_segments (session_id, start_ms);

CREATE TABLE stories (
    id                     TEXT PRIMARY KEY CHECK (id GLOB 'prj_*' AND length(id) = 30),
    session_id             TEXT REFERENCES sessions (id) ON DELETE RESTRICT,
    title                  TEXT NOT NULL,
    preset                 TEXT CHECK (preset IN ('moment', 'short', 'extended_short', 'highlight', 'compilation')),
    score                  REAL,
    score_components_json  TEXT,
    timeline_json          TEXT NOT NULL,
    layout_json            TEXT,
    review_state           TEXT NOT NULL CHECK (review_state IN ('suggested', 'accepted', 'rejected', 'edited')),
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE INDEX stories_session ON stories (session_id);

CREATE TABLE render_jobs (
    id             TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    story_id       TEXT NOT NULL REFERENCES stories (id) ON DELETE CASCADE,
    preset_id      TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('queued', 'rendering', 'ready', 'cancelled', 'failed')),
    progress       REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    output_path    TEXT,
    manifest_path  TEXT,
    error_json     TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX render_jobs_story ON render_jobs (story_id);

CREATE TABLE jobs (
    id              TEXT PRIMARY KEY CHECK (id GLOB 'job_*' AND length(id) = 30),
    kind            TEXT NOT NULL CHECK (kind IN ('import', 'analyze', 'proxy', 'transcribe', 'index', 'render')),
    state           TEXT NOT NULL CHECK (state IN ('queued', 'probing', 'fingerprinting', 'proxying', 'grouping',
                                                   'analyzing', 'transcribing', 'indexing', 'rendering', 'ready',
                                                   'cancelled', 'failed')),
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
CREATE INDEX jobs_state ON jobs (state);

CREATE TABLE tags (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at  TEXT NOT NULL
);

CREATE TABLE collections (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at  TEXT NOT NULL
);

-- Exactly one target per item; each target cascades so collections never dangle.
CREATE TABLE collection_items (
    id             INTEGER PRIMARY KEY,
    collection_id  INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    session_id     TEXT REFERENCES sessions (id) ON DELETE CASCADE,
    story_id       TEXT REFERENCES stories (id) ON DELETE CASCADE,
    event_id       TEXT REFERENCES events (id) ON DELETE CASCADE,
    position       INTEGER NOT NULL CHECK (position >= 0),
    added_at       TEXT NOT NULL,
    CHECK ((session_id IS NOT NULL) + (story_id IS NOT NULL) + (event_id IS NOT NULL) = 1),
    UNIQUE (collection_id, position)
);
CREATE INDEX collection_items_collection ON collection_items (collection_id);

CREATE TABLE watched_folders (
    id           INTEGER PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    source_kind  TEXT NOT NULL CHECK (source_kind IN
                     ('xbox', 'playstation', 'obs', 'capture_card', 'phone_upload', 'other')),
    enabled      INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at   TEXT NOT NULL
);

CREATE TABLE settings (
    key         TEXT PRIMARY KEY CHECK (length(key) BETWEEN 1 AND 128),
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
