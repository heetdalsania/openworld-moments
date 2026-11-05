# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database maintenance commands.

    uv run python -m openworld_moments.storage status  <library>/database.sqlite3
    uv run python -m openworld_moments.storage migrate <library>/database.sqlite3
    uv run python -m openworld_moments.storage backup  <library>/database.sqlite3

Output is JSON. Exit codes: 0 ok, 1 unhealthy or failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from openworld_moments.storage.database import Database, MigrationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openworld_moments.storage")
    parser.add_argument("command", choices=["status", "migrate", "backup"])
    parser.add_argument("database", type=Path, help="path to database.sqlite3")
    args = parser.parse_args(argv)
    database = Database(args.database)

    if args.command == "status":
        if not args.database.exists():
            print(json.dumps({"error": "database does not exist"}))
            return 1
        health = database.health()
        print(json.dumps({**asdict(health), "ok": health.ok}))
        return 0 if health.ok else 1

    if args.command == "migrate":
        try:
            report = database.migrate()
        except MigrationError as exc:
            print(
                json.dumps(
                    {"error": str(exc), "version": exc.version, "backup": str(exc.backup_path)}
                )
            )
            return 1
        print(json.dumps({**asdict(report), "backup_path": str(report.backup_path or "") or None}))
        return 0

    with closing(database.connect()) as conn:
        path = database.backup(conn, label=f"v{database.schema_version(conn)}-manual")
    print(json.dumps({"backup_path": str(path)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
