-- SPDX-License-Identifier: AGPL-3.0-or-later
-- No copied OCR/transcript text: only creator configuration and hashed decisions.
CREATE TABLE privacy_reviews (
    project_id TEXT PRIMARY KEY REFERENCES stories(id) ON DELETE CASCADE,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    token TEXT,
    decisions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(decisions_json)),
    acknowledged INTEGER NOT NULL DEFAULT 0 CHECK (acknowledged IN (0, 1))
);
