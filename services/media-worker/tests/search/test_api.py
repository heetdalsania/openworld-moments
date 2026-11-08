# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search, index and collection routes through the HTTP API."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import BUILTIN_HANDLERS, index_handler
from openworld_moments.storage import Database
from openworld_moments.storage.repositories import SCHEMA_VERSION
from tests.search.conftest import Library
from tests.worker.conftest import wait_for


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Library]]:
    database = Database.open(tmp_path / "library.sqlite3")
    token = secrets.token_hex(32)
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    handlers = {**BUILTIN_HANDLERS, "index": index_handler(database)}
    with TestClient(create_app(JobEngine(database, handlers), settings)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, Library(database)


def test_search_route_and_errors(api: tuple[TestClient, Library]) -> None:
    client, lib = api
    sid = lib.session("Heist night")
    lib.span(sid, None, "the heist begins")
    response = client.post(
        "/v1/search", json={"query": "heist", "filters": {"kinds": ["transcript"]}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == SCHEMA_VERSION and body["total"] == 1
    assert body["items"][0]["kind"] == "transcript"
    bad_query = client.post("/v1/search", json={"query": "h*"})
    assert bad_query.status_code == 422 and bad_query.json()["code"] == "search.prefix_too_short"
    for payload in (
        {"query": "x" * 257},
        {"filters": {"kinds": ["video"]}},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"unknown": True},
        {"filters": {"min_confidence": "high"}},
    ):
        refused = client.post("/v1/search", json=payload)
        assert refused.status_code == 422 and refused.json()["code"] == "request.invalid", payload


def test_index_status_rebuild_job_and_clear(api: tuple[TestClient, Library]) -> None:
    client, lib = api
    sid = lib.session()
    lib.span(sid, None, "words to find")
    status = client.get("/v1/search/index?check=true").json()
    assert status["status"] == "current" and status["checked"] is True
    cleared = client.delete("/v1/search/index")
    assert cleared.status_code == 200 and cleared.json()["status"] == "cleared"
    assert client.post("/v1/search", json={"query": "words"}).json()["index_status"] == "cleared"
    job = client.post("/v1/search/index/rebuild", json={})
    assert job.status_code == 201 and job.json()["kind"] == "index"
    job_id = job.json()["id"]

    def finished() -> Any:
        current = client.get(f"/v1/jobs/{job_id}").json()
        return current if current["state"] in ("ready", "failed") else None

    done = wait_for(finished)
    assert done["state"] == "ready" and done["result"] == {"documents": 2}
    assert client.get("/v1/search/index").json()["status"] == "current"
    assert client.post("/v1/search", json={"query": "words"}).json()["total"] == 1
    refused = client.post("/v1/search/index/rebuild", json={"force": True})
    assert refused.status_code == 422


def test_collection_routes(api: tuple[TestClient, Library]) -> None:
    client, lib = api
    sid = lib.session("Rooftop chase")
    aid = lib.clip(sid)
    tid = lib.span(sid, aid, "jump across")
    manual = client.post("/v1/collections", json={"name": "Picks"})
    assert manual.status_code == 201
    cid = manual.json()["id"]
    added = client.post(f"/v1/collections/{cid}/items", json={"kind": "transcript", "id": tid})
    assert added.status_code == 201 and added.json()["added"] is True
    repeat = client.post(f"/v1/collections/{cid}/items", json={"kind": "transcript", "id": tid})
    assert repeat.status_code == 200 and repeat.json()["added"] is False
    for wrong in (
        {"kind": "clip", "id": sid},
        {"kind": "transcript", "id": "ses_01JCBQ00000000000000000002"},
        {"kind": "session", "id": "not-an-id"},
        {"kind": "transcript", "id": True},
    ):
        assert client.post(f"/v1/collections/{cid}/items", json=wrong).status_code == 422, wrong
    page = client.get(f"/v1/collections/{cid}").json()
    assert page["total"] == 1 and page["items"][0]["transcript_id"] == tid
    ruled = client.post(
        "/v1/collections",
        json={"name": "Chases", "rule": {"version": 1, "query": "chase", "filters": {}}},
    )
    assert ruled.status_code == 201
    rule_page = client.get(f"/v1/collections/{ruled.json()['id']}").json()
    assert rule_page["items"][0]["key"] == f"session:{sid}"
    assert rule_page["items"][0]["reasons"][0]["criterion"] == "text"
    assert [c["name"] for c in client.get("/v1/collections").json()] == ["Chases", "Picks"]
    renamed = client.put(f"/v1/collections/{cid}", json={"name": "Best"})
    assert renamed.json()["name"] == "Best"
    item_id = page["items"][0]["item_id"]
    assert client.delete(f"/v1/collections/{cid}/items/{item_id}").status_code == 200
    assert client.delete(f"/v1/collections/{cid}/items/{item_id}").status_code == 404
    assert client.delete(f"/v1/collections/{cid}").status_code == 200
    assert client.get(f"/v1/collections/{cid}").status_code == 404
    assert client.get("/v1/collections/col_bad").status_code == 404
    assert client.post("/v1/collections", json={"name": ""}).status_code == 422
    duplicate = client.post("/v1/collections", json={"name": "chases"})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "collection.name_taken"
