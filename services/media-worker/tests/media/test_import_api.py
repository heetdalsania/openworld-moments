# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import, asset, relink, and source-check endpoints, idempotency keys, and crash requeue."""

from __future__ import annotations

import secrets
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.tools import ToolInfo
from openworld_moments.storage import Database, JobRepository, transaction
from tests.media.test_import import FixedTools
from tests.worker.conftest import wait_for


def _make_client(library: Path, ffprobe: ToolInfo) -> TestClient:
    token = secrets.token_hex(32)
    database = Database.open(library / "database.sqlite3")
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    tools = FixedTools(ffprobe)
    engine = JobEngine(database, build_handlers(tools, database=database))
    client = TestClient(create_app(engine, settings))
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
def api(tmp_path: Path, ffprobe: ToolInfo) -> Iterator[TestClient]:
    with _make_client(tmp_path / "library", ffprobe) as client:
        yield client


@pytest.fixture
def clip(media_dir: Path, tmp_path: Path) -> Path:
    target = tmp_path / "captures" / "clip one.mp4"
    target.parent.mkdir()
    shutil.copyfile(media_dir / "h264_aac.mp4", target)
    return target


def _finished(client: TestClient, job_id: str) -> dict[str, Any]:
    def done() -> dict[str, Any] | None:
        job: dict[str, Any] = client.get(f"/v1/jobs/{job_id}").json()
        return job if job["state"] in ("ready", "failed", "cancelled") else None

    job: dict[str, Any] = wait_for(done, timeout=30)
    load("job", job)
    return job


def test_import_endpoint_round_trip(api: TestClient, clip: Path) -> None:
    body = {"paths": [str(clip.parent)], "mode": "managed", "recursive": True}
    created = api.post("/v1/imports", json=body)
    assert created.status_code == 201, created.text
    job = _finished(api, created.json()["id"])
    assert job["kind"] == "import" and job["state"] == "ready"
    assert job["params"] == {**body, "source_kind": "other"}
    assert job["message"] == "1 imported"
    asset_id = job["result"]["items"][0]["asset_id"]

    assert api.get(f"/v1/imports/{job['id']}").json() == job
    assets = api.get("/v1/assets").json()
    assert [a["id"] for a in assets] == [asset_id]
    asset = api.get(f"/v1/assets/{asset_id}").json()
    load("media-asset", asset)
    assert asset["import_mode"] == "managed" and "original_path" not in asset
    assert api.get("/v1/assets", params={"missing": True}).json() == []


def test_idempotency_key_returns_the_first_job(api: TestClient, clip: Path) -> None:
    body = {"paths": [str(clip)], "mode": "reference", "idempotency_key": "ui:import:1"}
    first = api.post("/v1/imports", json=body)
    again = api.post("/v1/imports", json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["idempotency_key"] == "ui:import:1"

    other = api.post("/v1/imports", json={**body, "mode": "managed"})
    assert other.status_code == 409 and other.json()["code"] == "job.idempotency_conflict"
    bad = api.post("/v1/imports", json={**body, "idempotency_key": "no spaces"})
    assert bad.status_code == 422
    assert len([j for j in api.get("/v1/jobs").json() if j["kind"] == "import"]) == 1


def test_failed_import_keeps_its_report(api: TestClient, media_dir: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    shutil.copyfile(media_dir / "garbage.mp4", bad)
    job = _finished(
        api, api.post("/v1/imports", json={"paths": [str(bad)], "mode": "reference"}).json()["id"]
    )
    assert job["state"] == "failed" and job["error"]["code"] == "media.damaged"
    assert job["result"]["items"][0]["error"]["code"] == "media.damaged"
    assert str(bad) not in job["error"]["message"]


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"paths": ["relative/clip.mp4"], "mode": "reference"}, "'paths[0]' must be absolute"),
        ({"paths": [], "mode": "reference"}, "'paths' must be a list"),
        ({"paths": ["/x.mp4"], "mode": "reference", "source_kind": "vhs"}, "'source_kind'"),
    ],
)
def test_invalid_import_requests(api: TestClient, body: dict[str, Any], fragment: str) -> None:
    response = api.post("/v1/imports", json=body)
    assert response.status_code == 422
    assert fragment in response.json()["message"]
    assert api.post("/v1/imports", json={"paths": ["/x.mp4"], "mode": "move"}).status_code == 422


def test_relink_and_source_check_endpoints(api: TestClient, clip: Path) -> None:
    job = _finished(
        api, api.post("/v1/imports", json={"paths": [str(clip)], "mode": "reference"}).json()["id"]
    )
    asset_id = job["result"]["items"][0]["asset_id"]
    moved = clip.with_name("moved.mp4")
    clip.rename(moved)

    check = _finished(api, api.post("/v1/assets/check-sources").json()["id"])
    assert check["result"]["missing_asset_ids"] == [asset_id]
    assert [a["id"] for a in api.get("/v1/assets", params={"missing": True}).json()] == [asset_id]

    relink = api.post(f"/v1/assets/{asset_id}/relink", json={"path": str(moved)})
    assert relink.status_code == 201
    done = _finished(api, relink.json()["id"])
    assert done["state"] == "ready", done
    assert done["result"] == {"asset_id": asset_id, "verified_by": "sha256"}
    assert "missing_at" not in api.get(f"/v1/assets/{asset_id}").json()

    assert api.get("/v1/assets/ast_01JCBQ00000000000000000000").status_code == 404
    bogus = api.post("/v1/assets/not-an-id/relink", json={"path": str(moved)})
    assert bogus.status_code == 422 and "'asset_id'" in bogus.json()["message"]
    assert api.get(f"/v1/imports/{check['id']}").status_code == 404  # not an import


def test_interrupted_import_is_requeued_and_completes(
    tmp_path: Path, ffprobe: ToolInfo, clip: Path
) -> None:
    library = tmp_path / "library"
    database = Database.open(library / "database.sqlite3")
    job_id = "job_01JCBQ00000000000000000055"
    with transaction(conn := database.connect()):
        JobRepository(conn).save(
            load(  # type: ignore[arg-type]
                "job",
                {
                    "schema_version": "1.3",
                    "id": job_id,
                    "kind": "import",
                    "state": "probing",  # the worker died mid-import
                    "params": {
                        "paths": [str(clip)],
                        "mode": "managed",
                        "recursive": False,
                        "source_kind": "other",
                    },
                    "attempt": 1,
                    "created_at": "2026-11-20T05:40:10Z",
                    "started_at": "2026-11-20T05:40:11Z",
                },
            )
        )
    conn.close()
    leftover = library / "staging" / "imports" / job_id / "import-x.part"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"partial copy")

    with _make_client(library, ffprobe) as client:
        job = _finished(client, job_id)
    assert job["state"] == "ready" and job["attempt"] == 2
    assert job["result"]["totals"]["imported"] == 1
    assert not leftover.exists()
