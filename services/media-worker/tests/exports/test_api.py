# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export routes through the HTTP API."""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import BUILTIN_HANDLERS
from openworld_moments.storage import Database
from tests.exports.conftest import PRJ, Fixture, build

RENDER = "job_01JCBQ00000000000000000042"
MANIFEST = {
    "app_version": "0.0.0",
    "created_at": "2026-11-21T10:00:02.000Z",
    "detectors": [{"id": "wanted-stars", "version": "0.3.0"}],
    "encoder": "libx264",
    "output": {"duration_ms": 4000, "sha256": "d" * 64, "size_bytes": 934591},
    "profiles": [{"id": "open-world-vi-1080p-en", "version": "1.0.0"}],
    "project_id": PRJ,
    "project_revision": 3,
    "render": {
        "fps": {"den": 1, "num": 30},
        "height": 720,
        "layout": "fit",
        "preset_id": "horizontal-720p30",
        "width": 1280,
    },
    "render_id": RENDER,
    "schema_version": "1.21",
    "segments": [{"in_ms": 0, "out_ms": 4000, "source": 0}],
    "sources": [{"original_name": "Capture 01 — Café.mp4", "sha256": "a" * 64}],
    "tools": {"ffmpeg": "7.1.1", "render_engine": "1.0.0"},
}


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Fixture]]:
    media = tmp_path / "media"
    media.mkdir()
    database = Database.open(tmp_path / "library" / "database.sqlite3")
    fixture = build(database, media)
    token = secrets.token_hex(32)
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    with TestClient(create_app(JobEngine(database, BUILTIN_HANDLERS), settings)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, fixture


def test_export_route(api: tuple[TestClient, Fixture]) -> None:
    client, fixture = api
    response = client.post(f"/v1/projects/{PRJ}/exports", json={"format": "otio"})
    assert response.status_code == 200
    body = response.json()
    assert body == fixture.export("otio")
    assert body["schema_version"] == "1.21" and body["filename"].endswith(".otio")
    for payload, status in (
        ({"format": "edl"}, 422),
        ({"format": "srt", "include_paths": True}, 422),
        ({"format": "otio", "path": "../outside.otio"}, 422),
        ({}, 422),
    ):
        refused = client.post(f"/v1/projects/{PRJ}/exports", json=payload)
        assert refused.status_code == status, payload
    assert client.post("/v1/projects/prj_bad/exports", json={"format": "srt"}).status_code == 404
    missing = client.post(
        "/v1/projects/prj_01JCBQ00000000000000000099/exports", json={"format": "srt"}
    )
    assert missing.status_code == 404 and missing.json()["code"] == "export.not_found"


def test_render_manifest_route(api: tuple[TestClient, Fixture]) -> None:
    client, fixture = api
    assert client.get(f"/v1/renders/{RENDER}/manifest").status_code == 404
    fixture.sql(
        "INSERT INTO render_jobs (id, story_id, preset_id, status, created_at) "
        "VALUES (?, ?, 'horizontal-720p30', 'rendering', '2026-11-21T10:00:00Z')",
        (RENDER, PRJ),
    )
    busy = client.get(f"/v1/renders/{RENDER}/manifest")
    assert busy.status_code == 409 and busy.json()["code"] == "export.manifest_unavailable"
    fixture.sql(
        "UPDATE render_jobs SET status = 'ready', manifest_json = ? WHERE id = ?",
        (json.dumps(MANIFEST, separators=(",", ":")), RENDER),
    )
    first = client.get(f"/v1/renders/{RENDER}/manifest").json()
    assert first == client.get(f"/v1/renders/{RENDER}/manifest").json()
    assert first["format"] == "manifest" and first["filename"] == f"{RENDER}.manifest.json"
    assert json.loads(first["content"]) == MANIFEST
    assert (
        first["content"]
        == json.dumps(MANIFEST, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    )
