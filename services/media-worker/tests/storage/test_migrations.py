# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from openworld_moments.storage import (
    AssetRepository,
    Database,
    EventRepository,
    JobRepository,
    Migration,
    MigrationError,
    SessionRepository,
    SettingsRepository,
    StorageError,
    StoryRepository,
)
from openworld_moments.storage.database import bundled_migrations, split_statements
from tests.storage.conftest import DATA_FIXTURES

CORE_TABLES = {
    "media_assets",
    "sessions",
    "session_assets",
    "events",
    "transcript_segments",
    "stories",
    "render_jobs",
    "tags",
    "collections",
    "collection_items",
    "watched_folders",
    "jobs",
    "settings",
}
MIGRATIONS = bundled_migrations()
HEAD = MIGRATIONS[-1].version


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def _broken(version: int) -> Migration:
    # The first statement succeeds; the second fails. Neither may persist.
    return Migration(
        version,
        "broken",
        "CREATE TABLE half_done (a INTEGER);\nINSERT INTO no_such_table VALUES (1);\n",
    )


def _database_at(path: Path, version: int) -> Database:
    """A database migrated to ``version`` and filled with that version's data fixture."""
    old = Database(path, migrations=MIGRATIONS[:version])
    old.migrate()
    fixture = DATA_FIXTURES / f"data_v{version:04d}.sql"
    with closing(old.connect()) as conn:
        conn.executescript(fixture.read_text("utf-8"))
    return old


# -- fresh install --------------------------------------------------------------------


def test_fresh_database_migrates_to_head(tmp_path: Path) -> None:
    database = Database.open(tmp_path / "database.sqlite3")
    with closing(database.connect()) as conn:
        assert database.schema_version(conn) == HEAD
        assert CORE_TABLES | {"schema_migrations"} <= _tables(conn)
        recorded = conn.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [(r[0], r[1]) for r in recorded] == [(m.version, m.checksum) for m in MIGRATIONS]
    health = database.health()
    assert health.ok, health
    assert health.journal_mode == "wal"
    assert not (tmp_path / "backups").exists(), "an empty database needs no backup"


def test_reopening_at_head_is_a_no_op(database: Database) -> None:
    report = database.migrate()
    assert report.applied == ()
    assert report.backup_path is None
    assert report.from_version == report.to_version == HEAD


def test_every_migration_has_a_data_fixture() -> None:
    for migration in MIGRATIONS:
        assert (DATA_FIXTURES / f"data_v{migration.version:04d}.sql").exists(), migration.name


# -- upgrades from committed fixtures -------------------------------------------------


@pytest.mark.parametrize("version", [m.version for m in MIGRATIONS], ids=lambda v: f"v{v:04d}")
def test_upgrade_from_fixture_preserves_data(tmp_path: Path, version: int) -> None:
    path = tmp_path / "database.sqlite3"
    _database_at(path, version)

    database = Database(path)
    report = database.migrate()
    assert report.to_version == HEAD
    if version < HEAD:
        assert report.backup_path is not None and report.backup_path.exists()

    assert database.health().ok
    with closing(database.connect()) as conn:
        # Every row in the fixture is still readable through the repositories.
        assets = AssetRepository(conn).all()
        sessions = SessionRepository(conn).all()
        assert assets and sessions
        assert SessionRepository(conn).assets(sessions[0].id)
        assert EventRepository(conn).list_for_session(sessions[0].id)
        assert JobRepository(conn).list_unfinished()
        story_id = conn.execute("SELECT id FROM stories").fetchone()[0]
        assert StoryRepository(conn).get(story_id).timeline.id == story_id
        assert SettingsRepository(conn).get("import.mode") == "reference"


# -- failure and recovery -------------------------------------------------------------


def test_failed_migration_rolls_back_and_keeps_a_backup(tmp_path: Path) -> None:
    path = tmp_path / "database.sqlite3"
    _database_at(path, HEAD)
    database = Database(path, migrations=[*MIGRATIONS, _broken(HEAD + 1)])

    with pytest.raises(MigrationError) as caught:
        database.migrate()

    err = caught.value
    assert err.version == HEAD
    assert err.backup_path is not None and err.backup_path.exists()
    assert str(err.backup_path) in str(err)
    with closing(database.connect()) as conn:
        assert database.schema_version(conn) == HEAD
        assert "half_done" not in _tables(conn)
        assert AssetRepository(conn).all(), "data must survive a failed migration"
    with closing(sqlite3.connect(err.backup_path)) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == HEAD
        assert backup.execute("SELECT count(*) FROM media_assets").fetchone()[0] > 0


def test_backup_can_be_restored(tmp_path: Path) -> None:
    path = tmp_path / "database.sqlite3"
    _database_at(path, HEAD)
    database = Database(path, migrations=[*MIGRATIONS, _broken(HEAD + 1)])
    with pytest.raises(MigrationError) as caught:
        database.migrate()
    backup = caught.value.backup_path
    assert backup is not None

    with closing(database.connect()) as conn:
        conn.execute("DELETE FROM settings")
    database.restore(backup)
    with closing(database.connect()) as conn:
        assert SettingsRepository(conn).get("import.mode") == "reference"


def test_edited_migration_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "database.sqlite3"
    Database.open(path)
    first = MIGRATIONS[0]
    edited = Migration(first.version, first.name, first.sql + "\n-- edited\n")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        Database(path, migrations=[edited, *MIGRATIONS[1:]]).migrate()


def test_database_newer_than_the_app_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "database.sqlite3"
    Database.open(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {HEAD + 1}")
    with pytest.raises(MigrationError, match="newer than this app supports"):
        Database(path).migrate()


def test_migration_numbers_must_be_contiguous(tmp_path: Path) -> None:
    gap = Migration(HEAD + 2, "skipped", "SELECT 1;")
    with pytest.raises(StorageError, match="without gaps"):
        Database(tmp_path / "x.sqlite3", migrations=[*MIGRATIONS, gap])


def test_split_statements_handles_comments_and_quoted_semicolons() -> None:
    sql = (
        "-- header\nCREATE TABLE t (a TEXT); -- trailing\n\nINSERT INTO t VALUES ('x;y');\n-- end\n"
    )
    assert split_statements(sql) == [
        "CREATE TABLE t (a TEXT); -- trailing",
        "INSERT INTO t VALUES ('x;y');",
    ]


def test_incomplete_statement_is_rejected() -> None:
    with pytest.raises(StorageError, match="incomplete"):
        split_statements("CREATE TABLE t (a TEXT)")
