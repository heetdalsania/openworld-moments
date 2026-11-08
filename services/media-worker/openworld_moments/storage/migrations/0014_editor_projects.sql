-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Current autosave and its previous committed snapshot change atomically with stories.
CREATE TABLE editor_projects (
    project_id TEXT PRIMARY KEY REFERENCES stories(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    document_json TEXT NOT NULL CHECK (json_valid(document_json)),
    recovery_json TEXT CHECK (recovery_json IS NULL OR json_valid(recovery_json)),
    saved_at TEXT NOT NULL
);
