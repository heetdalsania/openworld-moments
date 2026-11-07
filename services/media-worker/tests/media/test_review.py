# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import secrets
from pathlib import Path

from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.__main__ import demo
from openworld_moments.detectors.profiles import ProfileCatalog
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import Database
from tests.worker.conftest import wait_for


def test_real_review_api_analyze_correct_manual_and_reconcile(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo
) -> None:
    result = demo(tmp_path, ProfileCatalog(), tools)
    analyzed = result["analysis"]
    assert isinstance(analyzed, dict)
    sid = analyzed["session_id"]
    database = Database.open(tmp_path / "library/database.sqlite3")
    derived = DerivedMedia(database, tools)
    settings = ApiSettings(
        secrets.token_hex(32), frozenset({"testserver"}), require_loopback_peer=False
    )
    engine = JobEngine(database, build_handlers(tools, database=database, derived=derived))
    route = f"/v1/sessions/{sid}/review"
    with TestClient(create_app(engine, settings, derived=derived)) as client:
        assert client.get(route).status_code == 401
        client.headers["Authorization"] = f"Bearer {settings.token}"
        page = client.get(route).json()
        item = page["items"][0]
        eid = item["original"]["id"]
        original = client.get("/v1/events", params={"session_id": sid}).json()[0]
        correction = {
            "layout_key": page["layout_key"],
            "expected_revision": 0,
            "action": "correct",
            "type": "openworld.reviewed",
            "start_ms": 250,
            "end_ms": 1750,
        }
        changed = client.post(f"{route}/{eid}", json=correction)
        assert (
            changed.status_code == 200
            and changed.json()["effective"]["review_state"] == "corrected"
        )
        assert changed.json()["original"] == original
        assert client.get("/v1/events", params={"session_id": sid}).json()[0] == original
        assert client.post(f"{route}/{eid}", json=correction).status_code == 409
        manual = {
            "layout_key": page["layout_key"],
            "type": "openworld.manual",
            "start_ms": 1000,
            "end_ms": 1500,
        }
        assert client.post(route, json={**manual, "start_ms": 1600}).status_code == 422
        added = client.post(route, json=manual)
        assert added.status_code == 201
        job = client.post(
            f"/v1/sessions/{sid}/analyze", json={"profile_id": "generic-open-world", "force": True}
        ).json()
        wait_for(lambda: client.get(f"/v1/jobs/{job['id']}").json()["state"] in ("ready", "failed"))
        assert client.get(f"/v1/jobs/{job['id']}").json()["state"] == "ready"
        after = client.get(route).json()
        archived = next(i for i in after["items"] if i["original"]["id"] == eid)
        assert (
            archived["status"] == "superseded"
            and archived["effective"]["type"] == "openworld.reviewed"
        )
        assert any(
            i["original"]["id"] == added.json()["original"]["id"] and i["status"] == "current"
            for i in after["items"]
        )
        assert client.get(route, params={"limit": 1}).json()["total"] == 3
        assert client.get("/v1/sessions/ses_missing/review").status_code == 404
        assert client.post(route, json={**manual, "confidence": 1}).status_code == 422
    with contextlib.closing(database.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM event_decisions").fetchone()[0] == 1
