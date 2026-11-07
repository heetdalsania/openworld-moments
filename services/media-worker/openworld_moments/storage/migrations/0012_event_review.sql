-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M19: immutable observations and append-only human decisions. Producer caches
-- continue to own the replaceable events table; these snapshots survive reruns.
CREATE TABLE event_observations (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    original_json TEXT NOT NULL,
    layout_key TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX event_observations_session ON event_observations(session_id, created_at, event_id);
CREATE TABLE event_decisions (
    event_id TEXT NOT NULL REFERENCES event_observations(event_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision > 0),
    decision_json TEXT NOT NULL,
    PRIMARY KEY(event_id, revision)
);
