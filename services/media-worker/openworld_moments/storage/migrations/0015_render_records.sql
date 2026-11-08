-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M24: render records. The existing render_jobs table gains the project revision,
-- the chosen encoder, the normalized render plan, the output validation, the
-- validated output (library-relative), an offered CPU fallback and the finish time.
-- A row is 'ready' only after its output passed validation and was moved into place.
ALTER TABLE render_jobs ADD COLUMN project_revision INTEGER CHECK (project_revision >= 0);
ALTER TABLE render_jobs ADD COLUMN encoder TEXT;
ALTER TABLE render_jobs ADD COLUMN plan_json TEXT;
ALTER TABLE render_jobs ADD COLUMN validation_json TEXT;
ALTER TABLE render_jobs ADD COLUMN output_json TEXT;
ALTER TABLE render_jobs ADD COLUMN fallback_json TEXT;
ALTER TABLE render_jobs ADD COLUMN finished_at TEXT;
