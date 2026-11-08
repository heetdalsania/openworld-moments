-- SPDX-License-Identifier: AGPL-3.0-or-later
-- M27: the canonical export manifest of each completed render, stored with the
-- record so re-exporting it is byte-stable even if the sidecar file is removed.
-- It names source hashes and versions only, never paths.
ALTER TABLE render_jobs ADD COLUMN manifest_json TEXT CHECK (manifest_json IS NULL OR json_valid(manifest_json));
