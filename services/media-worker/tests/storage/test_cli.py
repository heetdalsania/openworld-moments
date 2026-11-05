# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openworld_moments.storage.__main__ import main
from openworld_moments.storage.database import bundled_migrations

HEAD = bundled_migrations()[-1].version


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, object]]:
    code = main(list(args))
    return code, json.loads(capsys.readouterr().out)


def test_status_migrate_and_backup(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "database.sqlite3")

    code, out = _run(capsys, "status", db)
    assert code == 1 and "does not exist" in str(out["error"])

    code, out = _run(capsys, "migrate", db)
    assert code == 0 and out["to_version"] == HEAD and out["backup_path"] is None

    code, out = _run(capsys, "status", db)
    assert code == 0 and out["ok"] is True and out["pending_migrations"] == []

    code, out = _run(capsys, "backup", db)
    assert code == 0 and Path(str(out["backup_path"])).exists()
    assert Path(str(out["backup_path"])).parent == tmp_path / "backups"
