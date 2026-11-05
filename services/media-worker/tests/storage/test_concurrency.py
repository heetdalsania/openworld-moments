# SPDX-License-Identifier: AGPL-3.0-or-later
"""WAL behavior: readers proceed during a write, and committed data survives reopening."""

from __future__ import annotations

import threading
import time
from contextlib import closing
from pathlib import Path

from openworld_moments.storage import Database, SettingsRepository, transaction


def test_reader_is_not_blocked_by_an_open_write(database: Database) -> None:
    with closing(database.connect()) as writer, closing(database.connect()) as reader:
        with transaction(writer):
            SettingsRepository(writer).set("a", 1)
        writer.execute("BEGIN IMMEDIATE")
        SettingsRepository(writer).set("a", 2)  # uncommitted

        started = time.monotonic()
        assert SettingsRepository(reader).get("a") == 1  # sees the last committed value
        assert time.monotonic() - started < 1.0, "reader waited on the writer"

        writer.execute("COMMIT")
        assert SettingsRepository(reader).get("a") == 2


def test_concurrent_readers_alongside_one_writer(database: Database) -> None:
    errors: list[BaseException] = []
    stop = threading.Event()
    writes = 200

    def write() -> None:
        try:
            with closing(database.connect()) as conn:
                for i in range(writes):
                    with transaction(conn):
                        SettingsRepository(conn).set("counter", i)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            stop.set()

    def read() -> None:
        try:
            with closing(database.connect()) as conn:
                last = -1
                while not stop.is_set():
                    value = SettingsRepository(conn).get("counter", -1)
                    assert value >= last, "readers must never see values go backwards"
                    last = value
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=write)] + [threading.Thread(target=read) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    with closing(database.connect()) as conn:
        assert SettingsRepository(conn).get("counter") == writes - 1


def test_committed_writes_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "database.sqlite3"
    first = Database.open(path)
    conn = first.connect()
    with transaction(conn):
        SettingsRepository(conn).set("durable", {"ok": True})
    assert (tmp_path / "database.sqlite3-wal").exists(), "expected WAL mode"
    conn.close()

    reopened = Database.open(path)
    with closing(reopened.connect()) as conn:
        assert SettingsRepository(conn).get("durable") == {"ok": True}
    assert reopened.health().ok
