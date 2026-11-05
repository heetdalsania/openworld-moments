# Fixtures

- `synthetic/` — generated test media and frames. Prefer generating fixtures in
  tests over committing binaries.
- `manifests/` — evaluation manifests that may reference footage stored
  **outside** the repository.

Never commit leaked or pre-release footage, official trailers, or extracted game
assets. Media file extensions are ignored by `.gitignore` on purpose.
