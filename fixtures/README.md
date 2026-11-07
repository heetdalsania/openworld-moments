# Fixtures

- `synthetic/` — generated test media and frames. Prefer generating fixtures in
  tests over committing binaries.
- `manifests/` — evaluation manifests that may reference footage stored
  **outside** the repository.

M16's [wanted-v1 manifest](./manifests/wanted-v1.json) records original mathematical
star/disc recipes and an explicit synthetic case table. Its independent scanline
renderer lives in `detectors/wanted_fixtures.py`; tests generate all media in
scratch directories. Fixture pixels are AGPL-3.0-or-later, with no third-party art.

Never commit leaked or pre-release footage, official trailers, or extracted game
assets. Media file extensions are ignored by `.gitignore` on purpose.
