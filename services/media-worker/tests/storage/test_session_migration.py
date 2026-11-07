# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migration 0008 (M11): container times backfilled, jobs keep their rows, 'group' allowed."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from openworld_moments.storage import Database, JobRepository
from openworld_moments.storage.database import bundled_migrations

FIXTURES = Path(__file__).parent / "fixtures"


def test_upgrade_from_v7_backfills_container_times(tmp_path: Path) -> None:
    path = tmp_path / "database.sqlite3"
    old = Database(path, migrations=bundled_migrations()[:7])
    old.migrate()
    with closing(old.connect()) as conn:
        conn.executescript((FIXTURES / "data_v0007.sql").read_text("utf-8"))
        conn.execute(  # one asset whose estimate came from the container
            "UPDATE media_assets SET captured_at = '2026-11-20T03:14:22.000Z', "
            "captured_at_basis_json = '[\"container_metadata\"]' "
            "WHERE id = (SELECT min(id) FROM media_assets)"
        )
        conn.commit()
        before = conn.execute(
            "SELECT id, captured_at, captured_at_basis_json FROM media_assets ORDER BY id"
        ).fetchall()
        jobs = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
    Database(path).migrate()
    with closing(Database(path).connect()) as conn:
        after = {
            r["id"]: r["container_created_at"]
            for r in conn.execute("SELECT id, container_created_at FROM media_assets")
        }
        for asset_id, captured_at, basis in before:
            expected = captured_at if basis == '["container_metadata"]' else None
            assert after[asset_id] == expected
        assert "2026-11-20T03:14:22.000Z" in after.values()
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == jobs
        assert JobRepository(conn).list_unfinished()
        conn.execute(
            "INSERT INTO jobs (id, kind, state, created_at) VALUES "
            "('job_01JCBQ00000000000000000GRP', 'group', 'queued', '2026-11-21T09:00:00Z')"
        )
