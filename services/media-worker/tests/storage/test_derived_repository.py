# SPDX-License-Identifier: AGPL-3.0-or-later
"""derived_artifacts (migration 0007, M08): rows, failures, constraints, cascades."""

from __future__ import annotations

import sqlite3

import pytest

from openworld_moments.storage import (
    AssetRepository,
    ConflictError,
    DerivedArtifactRepository,
    DerivedArtifactRow,
    transaction,
)
from tests.storage.test_repositories import ASSET_ID, NOW, _asset

KEY = "3f" * 32
OTHER_KEY = "4a" * 32
RECIPE = {"preset": {"id": "proxy-h264-sdr", "version": 1}, "tool": {"ffmpeg": "7.1.1"}}


def _ready(key: str = KEY) -> DerivedArtifactRow:
    return DerivedArtifactRow(
        asset_id=ASSET_ID,
        kind="proxy",
        status="ready",
        cache_key=key,
        recipe=RECIPE,
        info={"width": 1280, "height": 720},
        relpath=f"derived/{ASSET_ID}/proxy-{key[:16]}.mp4",
        size_bytes=1234,
        sha256="5b" * 32,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def repo(conn: sqlite3.Connection) -> DerivedArtifactRepository:
    with transaction(conn):
        AssetRepository(conn).add(_asset())
    return DerivedArtifactRepository(conn)


def test_put_get_and_replace(repo: DerivedArtifactRepository, conn: sqlite3.Connection) -> None:
    with transaction(conn):
        repo.put(_ready())
    assert repo.get(ASSET_ID, "proxy") == _ready()
    assert repo.get(ASSET_ID, "waveform") is None
    with transaction(conn):
        repo.put(_ready(OTHER_KEY))
    assert repo.get(ASSET_ID, "proxy").cache_key == OTHER_KEY  # type: ignore[union-attr]
    assert list(repo.for_asset(ASSET_ID)) == ["proxy"]
    assert repo.relpaths() == [f"derived/{ASSET_ID}/proxy-{OTHER_KEY[:16]}.mp4"]


def test_failure_keeps_a_ready_artifact(
    repo: DerivedArtifactRepository, conn: sqlite3.Connection
) -> None:
    error = {"code": "derived.disk_full", "message": "Full.", "retryable": True}
    with transaction(conn):
        repo.record_failure(ASSET_ID, "waveform", cache_key=KEY, recipe=RECIPE, error=error)
        repo.put(_ready())
        repo.record_failure(ASSET_ID, "proxy", cache_key=OTHER_KEY, recipe=RECIPE, error=error)
    failed = repo.get(ASSET_ID, "waveform")
    assert failed is not None and failed.status == "failed" and failed.relpath is None
    kept = repo.get(ASSET_ID, "proxy")
    assert kept is not None and kept.status == "ready" and kept.cache_key == KEY
    assert kept.last_error == error
    assert repo.relpaths() == [_ready().relpath]


def test_a_ready_row_must_name_its_file(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        AssetRepository(conn).add(_asset())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO derived_artifacts (asset_id, kind, status, cache_key, recipe_json, "
            "updated_at) VALUES (?, 'proxy', 'ready', ?, '{}', ?)",
            (ASSET_ID, KEY, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO derived_artifacts (asset_id, kind, status, cache_key, recipe_json, "
            "relpath, updated_at) VALUES (?, 'proxy', 'failed', ?, '{}', '/etc/passwd', ?)",
            (ASSET_ID, KEY, NOW),
        )


def test_unknown_asset_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(ConflictError), transaction(conn):
        DerivedArtifactRepository(conn).put(_ready())


def test_rows_cascade_with_their_asset(
    repo: DerivedArtifactRepository, conn: sqlite3.Connection
) -> None:
    with transaction(conn):
        repo.put(_ready())
        conn.execute("DELETE FROM media_assets WHERE id = ?", (ASSET_ID,))
    assert repo.for_asset(ASSET_ID) == {}
