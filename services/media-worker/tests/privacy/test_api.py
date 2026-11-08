# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.exports.conftest import PRJ, Fixture
from tests.exports.test_api import api as api


def test_authenticated_review_routes(api: tuple[TestClient, Fixture]) -> None:
    client, _ = api
    path = f"/v1/projects/{PRJ}/privacy-review"
    assert client.delete(path).status_code == 200
    report = client.get(path).json()
    assert not report["current"]
    assert client.post(f"/v1/projects/{PRJ}/exports", json={"format": "project"}).status_code == 409
    payload = dict(
        token=report["token"],
        acknowledged=True,
        decisions=[dict(id=f["id"], state="ignore") for f in report["flags"]],
    )
    assert client.post(path, json=payload).json()["current"]
    assert client.post(f"/v1/projects/{PRJ}/exports", json={"format": "project"}).status_code == 200
    assert client.put(path, json=dict(labels=["finale"], ranges=[])).status_code == 200
    assert client.post(path, json=payload).status_code == 409
    assert client.put(path, json=dict(labels=[""], ranges=[])).status_code == 422
    assert client.put(path, json=dict(labels=[], ranges=[], path="../file")).status_code == 422
    assert (
        client.get("/v1/projects/prj_01JCBQ00000000000000000099/privacy-review").status_code == 404
    )
    assert client.delete(f"/v1/projects/{PRJ}/privacy-text").status_code == 200
    client.headers.pop("Authorization")
    assert client.get(path).status_code == 401
