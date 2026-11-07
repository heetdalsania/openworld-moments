# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import hashlib
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
from openworld_moments.storage import Database, StoryRepository
from tests.worker.conftest import wait_for


def test_real_detect_review_generate_accept_regenerate_and_preserve_sources(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo
) -> None:
    result = demo(tmp_path, ProfileCatalog(), tools)
    analyzed = result["analysis"]
    assert isinstance(analyzed, dict)
    sid = analyzed["session_id"]
    media = tmp_path / "synthetic signal.mp4"
    before = (hashlib.sha256(media.read_bytes()).hexdigest(), media.stat().st_mtime_ns)
    db = Database.open(tmp_path / "library/database.sqlite3")
    derived = DerivedMedia(db, tools)
    engine = JobEngine(db, build_handlers(tools, database=db, derived=derived))
    settings = ApiSettings(
        secrets.token_hex(32), frozenset({"testserver"}), require_loopback_peer=False
    )
    route = f"/v1/sessions/{sid}/stories"
    with TestClient(create_app(engine, settings, derived=derived)) as client:
        assert client.get(route).status_code == 401
        client.headers["Authorization"] = f"Bearer {settings.token}"
        review = client.get(f"/v1/sessions/{sid}/review").json()
        event = review["items"][0]
        changed = client.post(
            f"/v1/sessions/{sid}/review/{event['original']['id']}",
            json={
                "layout_key": review["layout_key"],
                "expected_revision": 0,
                "action": "correct",
                "type": "openworld.mission_completed",
                "start_ms": 500,
                "end_ms": 2000,
            },
        )
        assert changed.status_code == 200
        assert client.get(route).json()["total"] == 0
        response = client.post(route, json={"preset": "moment", "idempotency_key": "m20-e2e"})
        assert response.status_code == 201
        job = response.json()
        assert job["kind"] == "story"
        assert (
            client.post(route, json={"preset": "moment", "idempotency_key": "m20-e2e"}).json()["id"]
            == job["id"]
        )
        wait_for(lambda: client.get(f"/v1/jobs/{job['id']}").json()["state"] in ("ready", "failed"))
        done = client.get(f"/v1/jobs/{job['id']}").json()
        assert done["state"] == "ready", done
        page = client.get(route, params={"preset": "moment"}).json()
        item = page["items"][0]
        candidate = item["candidate"]
        assert candidate["source_events"][0]["revision"] == 1
        assert candidate["source_ranges"][0]["source_out_ms"] == 3000
        cached_job = client.post(route, json={"preset": "moment"}).json()
        wait_for(
            lambda: (
                client.get(f"/v1/jobs/{cached_job['id']}").json()["state"] in ("ready", "failed")
            )
        )
        cached_done = client.get(f"/v1/jobs/{cached_job['id']}").json()
        assert cached_done["state"] == "ready", cached_done
        assert cached_done["result"]["cached"] is True
        assert cached_done["progress"] == {"done": 3, "total": 3}
        decision_route = f"{route}/{candidate['id']}/decision"
        decision = {
            "input_key": candidate["input_key"],
            "expected_revision": 0,
            "state": "accepted",
        }
        accepted = client.post(decision_route, json=decision)
        assert accepted.status_code == 200 and accepted.json()["project_id"] == candidate["id"]
        assert client.post(decision_route, json=decision).status_code == 409
        assert (
            client.post(
                decision_route, json={**decision, "expected_revision": 1, "title": "no"}
            ).status_code
            == 422
        )
        assert client.post(route, json={"preset": "moment", "force": True}).status_code == 201
        rejected = client.post(
            decision_route, json={**decision, "expected_revision": 1, "state": "rejected"}
        )
        assert rejected.status_code == 200
        assert client.get(route, params={"preset": "moment"}).json()["total"] == 0
        assert (
            client.get(route, params={"preset": "moment", "include_history": True}).json()["items"][
                0
            ]["review_state"]
            == "rejected"
        )
        assert client.get(route, params={"pre_roll_ms": -1}).status_code == 422
        assert client.post(route, json={"preset": "compilation"}).status_code == 422
        assert client.post(route, json={"preset": "short", "pre_roll_ms": True}).status_code == 422
        assert client.get("/v1/sessions/ses_missing/stories").status_code == 404
        assert client.post(f"{route}/prj_missing/decision", json=decision).status_code == 404
    with contextlib.closing(db.connect()) as conn:
        assert StoryRepository(conn).get(candidate["id"]).review_state == "rejected"
        assert conn.execute("SELECT count(*) FROM story_candidates").fetchone()[0] == 1
    assert (hashlib.sha256(media.read_bytes()).hexdigest(), media.stat().st_mtime_ns) == before
