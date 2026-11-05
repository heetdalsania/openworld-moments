# ADR-0003: Standard-library SQLite with an in-house migration runner

- Status: Accepted
- Date: 2026-11-05
- Milestone: M02
- Deciders: project maintainers

## Context

The worker owns canonical state in SQLite (spec §9.1, §9.7). M02 needs WAL
mode, versioned migrations for every core table, a backup before each
upgrade, recovery from a failed migration, and typed repositories. The worker
is later frozen into a Windows installer (M29), where every dependency adds
size, license review, and SBOM entries (M30).

## Decision

- Use Python's standard-library `sqlite3`. No ORM.
- Use a small in-house migration runner (`openworld_moments/storage/database.py`)
  instead of a migration library:
  - Migrations are forward-only SQL files `migrations/NNNN_name.sql`, numbered
    1..n without gaps, shipped inside the package.
  - Each migration runs in its own `BEGIN IMMEDIATE` transaction (SQLite DDL is
    transactional). Statements are split with `sqlite3.complete_statement`
    because `executescript()` commits implicitly.
  - `schema_migrations` records version, name, SHA-256 checksum, and time.
    `PRAGMA user_version` mirrors the latest version.
  - Applied migrations must never be edited. A checksum mismatch stops startup.
  - Before upgrading a database that holds data, the runner writes a copy with
    SQLite's online backup API to `<library>/backups/`.
  - A failing migration rolls back, leaves the database at the last good
    version, and raises `MigrationError` naming the backup.
- Repositories map the M01 contract models to normalized columns and validate
  every row they return through the contracts' `load()`.

## Consequences

- Zero new runtime dependencies; migrations are readable SQL a reviewer can
  check line by line.
- We own about 150 lines of runner code, covered by tests for fresh install,
  upgrade from committed data fixtures, failed migrations, edited migrations,
  and databases newer than the app.
- No automatic down-migrations. Recovery is by restoring the pre-upgrade backup,
  which is safer for user libraries than reversing DDL.
- SQLite's limited `ALTER TABLE` means some future migrations will use the
  create-copy-swap pattern by hand.

## Alternatives considered

- **Alembic (+ SQLAlchemy):** mature, but brings SQLAlchemy into the packaged
  worker, needs batch mode for most SQLite changes, and still requires custom
  code for backups.
- **yoyo-migrations:** lighter, but adds a dependency for little beyond what the
  runner does, and its transaction handling around SQLite DDL would still need
  verification.
- **SQLModel/ORM repositories:** convenient, but hides SQL behind another layer
  and makes lossless contract round-trips harder to reason about.
