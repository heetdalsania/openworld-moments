# M05 — Safe import pipeline

## Objective

Implement idempotent reference-in-place and managed-copy imports through a staging boundary, using the M04 probe result as the gate.

## Dependencies

M04 merged.

## Required context

Read specification sections 8.1, 9.6, 14, and Epic B.

## In scope

- Single-file and recursive-folder import jobs.
- Reference and managed-copy modes.
- Staging directory for copied/uploaded media.
- Atomic promotion into content-addressed managed storage after validation.
- Import provenance and original-path tracking.
- Missing referenced-file detection and relink service.
- Idempotency keys and partial-failure reporting.

## Out of scope

- Duplicate/perceptual hashes beyond any temporary import key, watched folders, and phone upload.

## Implementation steps

1. Define import request/result contracts and batch semantics.
2. Implement file allowlist and size/regular-file checks.
3. Probe before database commit.
4. Copy through staging, verify byte count, then atomically promote.
5. Persist provenance only after successful validation.
6. Implement batch partial success without hiding failures.
7. Implement relink by verified file identity placeholder ready for M06.

## Acceptance criteria

- Reference import never moves or writes the source.
- Managed import survives interruption without exposing a partial library file.
- Repeating the same request does not create duplicate database rows.
- Recursive import cannot escape the selected root through symlink tricks.
- Unsupported media remains outside canonical storage.
- Missing references are visible and relinkable.

## Required validation

- Reference source hash/mtime test.
- Interrupted-copy recovery test.
- Symlink/path traversal test.
- Mixed-validity batch test.
- Disk-full or simulated write-failure test.

## Handoff

Document import API, staging cleanup, atomicity guarantees, and current identity limitation awaiting M06. Update M05.

