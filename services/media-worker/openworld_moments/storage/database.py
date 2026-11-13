# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite connections, migrations, backups, and health.

Migrations are numbered SQL files in ``migrations/`` (``0001_initial.sql``, ...).
Each runs in its own transaction and is recorded with a checksum in
``schema_migrations``; ``PRAGMA user_version`` mirrors the latest applied
version. Before upgrading a database that already holds data, a consistent copy
is written to the backup directory. See docs/architecture/storage.md.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

_MIGRATION_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
BUSY_TIMEOUT_MS = 5000


class StorageError(Exception):
    """Base class for persistence errors."""


class MigrationError(StorageError):
    """A migration could not be applied. The database is left at ``version``."""

    def __init__(self, message: str, *, version: int, backup_path: Path | None) -> None:
        detail = (
            f" A backup of the database before upgrading is at {backup_path}."
            if backup_path
            else ""
        )
        super().__init__(message + detail)
        self.version = version
        self.backup_path = backup_path


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationReport:
    from_version: int
    to_version: int
    applied: tuple[int, ...]
    backup_path: Path | None


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    """Support-bundle safe: no paths or user data."""

    schema_version: int
    head_version: int
    pending_migrations: tuple[int, ...]
    journal_mode: str
    foreign_keys: bool
    quick_check: str

    @property
    def ok(self) -> bool:
        return (
            not self.pending_migrations
            and self.journal_mode == "wal"
            and self.foreign_keys
            and self.quick_check == "ok"
        )


def utc_now() -> str:
    """Current time as a contract UtcTimestamp (millisecond precision, 'Z')."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def bundled_migrations() -> tuple[Migration, ...]:
    """Migrations shipped with the worker, validated to be contiguous from 0001."""
    folder = resources.files(__package__) / "migrations"
    found = []
    for entry in folder.iterdir():
        match = _MIGRATION_FILE.match(entry.name)
        if match:
            found.append(Migration(int(match.group(1)), match.group(2), entry.read_text("utf-8")))
    return validate_sequence(found)


def validate_sequence(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    ordered = tuple(sorted(migrations, key=lambda m: m.version))
    expected = list(range(1, len(ordered) + 1))
    if [m.version for m in ordered] != expected:
        raise StorageError(
            f"migrations must be numbered 1..n without gaps, got {[m.version for m in ordered]}"
        )
    return ordered


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("--")


def split_statements(sql: str) -> list[str]:
    """Split a migration script into statements without executescript().

    executescript() commits implicitly, which would break per-migration atomicity.
    Leading comment lines are dropped; comments after a statement stay with it.
    """
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        if not buffer and _is_blank_or_comment(line):
            continue
        buffer.append(line)
        if sqlite3.complete_statement("\n".join(buffer)):
            statements.append("\n".join(buffer).strip())
            buffer = []
    if buffer:
        raise StorageError("migration ends with an incomplete SQL statement")
    return statements


class Database:
    """A library database file. Open connections with :meth:`connect`."""

    def __init__(
        self,
        path: Path,
        *,
        backup_dir: Path | None = None,
        migrations: Sequence[Migration] | None = None,
    ) -> None:
        self.path = Path(path)
        self.backup_dir = backup_dir if backup_dir is not None else self.path.parent / "backups"
        self.migrations = (
            validate_sequence(migrations) if migrations is not None else bundled_migrations()
        )

    @property
    def head_version(self) -> int:
        return self.migrations[-1].version if self.migrations else 0

    @classmethod
    def validate_existing(cls, root: Path) -> None:
        """Identify a library before migrations or preference changes.

        First inspect the main database immutably, without sidecars. Only after
        identifying an OWM library may SQLite read an existing WAL in read-only
        mode. This checks committed version metadata after a crash, rather than
        accepting a stale main-file snapshot. No database writes are permitted.
        """
        try:
            candidate = root / "database.sqlite3"
            for entry in (
                candidate,
                candidate.with_name(candidate.name + "-wal"),
                candidate.with_name(candidate.name + "-shm"),
            ):
                if entry.is_symlink() or (entry.exists() and entry.stat().st_nlink != 1):
                    raise StorageError("Linked database files are not accepted")
            if not candidate.is_file():
                raise StorageError("Not a regular library database")
            path = candidate.resolve()
            database = cls(path)

            def inspect(uri: str) -> None:
                with closing(sqlite3.connect(uri, uri=True)) as conn:
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA trusted_schema = OFF")
                    conn.execute("PRAGMA query_only = ON")
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_schema WHERE type='table' "
                            "AND name IN ('schema_migrations', 'media_assets')"
                        )
                    }
                    if tables != {"schema_migrations", "media_assets"}:
                        raise StorageError("Not an OpenWorld Moments library")
                    current = database.schema_version(conn)
                    if current < 1:
                        raise StorageError("Not an initialized library")
                    database._verify_applied(conn, current)

            inspect(path.as_uri() + "?mode=ro&immutable=1")
            wal = path.with_name(path.name + "-wal")
            if wal.is_file() and wal.stat().st_size:
                inspect(path.as_uri() + "?mode=ro")
        except (sqlite3.Error, OSError, StorageError) as exc:
            raise StorageError(
                "The selected folder is not a verified OpenWorld Moments library. "
                "Close the app using that library and select its folder again. "
                "A newer library may require a newer app."
            ) from exc

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        backup_dir: Path | None = None,
        migrations: Sequence[Migration] | None = None,
    ) -> Database:
        """Create the file if needed and migrate it to head."""
        database = cls(path, backup_dir=backup_dir, migrations=migrations)
        database.migrate()
        return database

    def connect(self) -> sqlite3.Connection:
        """New connection in autocommit mode with WAL, foreign keys, and a busy timeout.

        Use :func:`transaction` for writes. One writer at a time is expected; WAL
        lets readers proceed while it writes.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        mode = self._enable_wal(conn)
        if mode != "wal":
            conn.close()
            raise StorageError(f"could not enable WAL mode (got {mode!r})")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @staticmethod
    def _enable_wal(conn: sqlite3.Connection) -> str:
        """Switch to WAL, retrying while another process holds the lock.

        Changing the journal mode needs an exclusive lock and SQLite can report
        "database is locked" immediately instead of honoring busy_timeout, which
        happens when several processes open a new library at the same moment.
        """
        deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                return str(conn.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or time.monotonic() >= deadline:
                    conn.close()
                    raise
                time.sleep(0.02)

    # -- migrations -----------------------------------------------------------------

    def schema_version(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def pending(self, conn: sqlite3.Connection) -> tuple[int, ...]:
        current = self.schema_version(conn)
        return tuple(m.version for m in self.migrations if m.version > current)

    def migrate(self) -> MigrationReport:
        """Apply pending migrations, backing up first if the database holds data.

        Safe to call from several processes at once: each migration re-reads the
        schema version after taking the write lock and skips work another process
        already finished.
        """
        with closing(self.connect()) as conn:
            # One read transaction, so the version and the ledger come from the same
            # snapshot even while another process commits a migration in between.
            conn.execute("BEGIN")
            try:
                current = self.schema_version(conn)
                self._verify_applied(conn, current)
            finally:
                conn.execute("COMMIT")
            todo = [m for m in self.migrations if m.version > current]
            if not todo:
                return MigrationReport(current, current, (), None)

            backup_path = self.backup(conn, label=f"v{current}") if current > 0 else None
            applied: list[int] = []
            for migration in todo:
                try:
                    with transaction(conn):
                        if self.schema_version(conn) >= migration.version:
                            continue  # applied by another process while we waited
                        self._ensure_ledger(conn)
                        for statement in split_statements(migration.sql):
                            conn.execute(statement)
                        conn.execute(
                            "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                            "VALUES (?, ?, ?, ?)",
                            (migration.version, migration.name, migration.checksum, utc_now()),
                        )
                        conn.execute(f"PRAGMA user_version = {migration.version:d}")
                        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                        if violations:
                            raise StorageError(f"foreign key violations: {len(violations)} rows")
                except (sqlite3.Error, StorageError) as exc:
                    raise MigrationError(
                        f"migration {migration.version:04d}_{migration.name} failed: {exc}. "
                        f"The database is unchanged at version {self.schema_version(conn)}.",
                        version=self.schema_version(conn),
                        backup_path=backup_path,
                    ) from exc
                applied.append(migration.version)
            final = self.schema_version(conn)
            self._verify_applied(conn, final)
            return MigrationReport(current, final, tuple(applied), backup_path)

    def _ensure_ledger(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )

    def _verify_applied(self, conn: sqlite3.Connection, current: int) -> None:
        if current > self.head_version:
            raise MigrationError(
                f"database schema version {current} is newer than this app supports "
                f"({self.head_version}). Update OpenWorld Moments to open this library.",
                version=current,
                backup_path=None,
            )
        if current == 0:
            return
        known = {m.version: m for m in self.migrations}
        rows = conn.execute("SELECT version, name, checksum FROM schema_migrations").fetchall()
        recorded = {row["version"] for row in rows}
        if recorded != set(range(1, current + 1)):
            raise MigrationError(
                f"migration ledger is inconsistent with schema version {current}",
                version=current,
                backup_path=None,
            )
        for row in rows:
            migration = known[row["version"]]
            if row["checksum"] != migration.checksum:
                raise MigrationError(
                    f"migration {migration.version:04d}_{migration.name} was changed after it "
                    "was applied. Applied migrations must never be edited; add a new one.",
                    version=current,
                    backup_path=None,
                )

    # -- backup and restore ---------------------------------------------------------

    def backup(self, conn: sqlite3.Connection, *, label: str) -> Path:
        """Write a consistent copy using SQLite's online backup API."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.backup_dir / f"{self.path.stem}-{stamp}-{label}.sqlite3"
        with closing(sqlite3.connect(target)) as dest:
            conn.backup(dest)
        return target

    def restore(self, backup_path: Path) -> None:
        """Replace the database contents with a backup. Close other connections first."""
        with closing(sqlite3.connect(backup_path)) as source, closing(self.connect()) as dest:
            source.backup(dest)

    # -- health ---------------------------------------------------------------------

    def health(self) -> DatabaseHealth:
        with closing(self.connect()) as conn:
            return DatabaseHealth(
                schema_version=self.schema_version(conn),
                head_version=self.head_version,
                pending_migrations=self.pending(conn),
                journal_mode=str(conn.execute("PRAGMA journal_mode").fetchone()[0]),
                foreign_keys=bool(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
                quick_check=str(conn.execute("PRAGMA quick_check").fetchone()[0]),
            )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception.

    IMMEDIATE takes the write lock up front so a writer fails fast (after the busy
    timeout) instead of deadlocking on upgrade from a read lock.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
