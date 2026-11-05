# M02 — Database and migrations

## Objective

Implement SQLite persistence, migrations, repository interfaces, and transactional guarantees for canonical application state.

## Dependencies

M01 merged.

## Required context

Read specification sections 9.6, 9.7, 13, and 14.3.

## In scope

- SQLite database creation in WAL mode.
- Versioned migrations for all core tables listed in specification section 9.7.
- Python repository layer with typed inputs/outputs.
- Transaction and foreign-key behavior.
- Backup-before-migration and failed-migration recovery.
- Temporary test database helpers.

## Out of scope

- FTS indexes, import logic, UI state, and media files.

## Implementation steps

1. Select and record the migration library.
2. Implement initial normalized schema and indexes.
3. Add repositories for assets, sessions, jobs, events, stories, and settings.
4. Enforce foreign keys, uniqueness, and delete policies.
5. Add migration backup and rollback behavior.
6. Add database health and schema-version inspection.
7. Document which state belongs in SQLite versus filesystem artifacts.

## Acceptance criteria

- A fresh database migrates to current head automatically.
- Repositories round-trip contract fixtures without lossy conversion.
- Asset deletion cannot silently orphan canonical session data.
- A simulated failed migration preserves a recoverable backup.
- Concurrent readers do not block the single writer in normal test scenarios.

## Required validation

- Migration up tests from empty database.
- Upgrade test from every committed migration fixture.
- Constraint and transaction rollback tests.
- WAL/reopen durability test.

## Handoff

List migration commands, repository interfaces, delete policies, and backup location. Update the M02 ledger entry.

