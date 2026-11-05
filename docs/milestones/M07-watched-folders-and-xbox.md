# M07 — Watched folders and Xbox onboarding

## Objective

Reliably import completed files from user-approved folders, with an onboarding path specifically explaining Xbox OneDrive capture synchronization.

## Dependencies

M05 merged.

## Required context

Read specification sections 6.1, 8.1.2, and 10.2.

## In scope

- Watched-folder persistence and enable/disable controls.
- Native filesystem events plus bounded reconciliation scan.
- File stabilization based on unchanged size/mtime, readable handle, and successful probe.
- Include/exclude patterns and recursion choice.
- Xbox/OneDrive onboarding copy that does not claim direct Xbox API access.
- Error/backoff behavior for unavailable cloud-synced files.

## Out of scope

- Connecting to OneDrive APIs, deleting cloud files, or phone uploads.

## Implementation steps

1. Add watched-folder contracts and database repository.
2. Implement Rust watcher and worker import handoff.
3. Implement stabilization timer and deduplicated event queue.
4. Add startup reconciliation and removable/unavailable-folder state.
5. Add onboarding and settings UI.
6. Add status showing last scan, queued files, and failures.
7. Document Xbox setup with an official-source link and current limitations.

## Acceptance criteria

- A slowly copied file is imported only after stabilization.
- Repeated OS events cause one import.
- Restart discovers files missed while the app was closed.
- Disabled folders do no work.
- Unavailable folders do not spam jobs or logs.
- The app never deletes or relocates watched source files.

## Required validation

- Slow-write test.
- Rename-into-folder test.
- Duplicate-event storm test.
- Restart reconciliation test.
- Offline folder/backoff test.

## Handoff

Document stabilization defaults, reconciliation interval, platform watcher differences, and Xbox onboarding path. Update M07.

