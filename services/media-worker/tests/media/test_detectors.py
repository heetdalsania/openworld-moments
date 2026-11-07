# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real derived input, job/API and CLI tests; all footage is generated."""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.__main__ import demo
from openworld_moments.detectors.inputs import content_hash, decode_frames
from openworld_moments.detectors.profiles import DEFAULT_CATALOG, ProfileCatalog
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.detectors.service import Analyzer
from openworld_moments.ids import new_id
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import Database, DerivedArtifactRepository
from tests.worker.conftest import wait_for


def test_generated_example_real_proxy_cache_and_original_preserved(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = demo(tmp_path, ProfileCatalog(), tools)
    analyzed = output["analysis"]
    assert isinstance(analyzed, dict)
    original = tmp_path / "synthetic signal.mp4"
    before = (hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns)
    database = Database.open(tmp_path / "library" / "database.sqlite3")
    derived = DerivedMedia(database, tools)
    analyzer = Analyzer(database, tools, derived)
    sid = analyzed["session_id"]
    aid = analyzed["outcomes"][0]["asset_id"]
    params = {"session_id": sid, "profile_id": "generic-open-world"}
    assert analyzer.run(params, job_id=new_id("job"))["outcomes"][0]["status"] == "cached"
    # A successful rerun replaces this producer's unreviewed events, not the source.
    result = analyzer.run({**params, "force": True}, job_id=new_id("job"))
    assert result["outcomes"][0]["status"] == "computed"
    assert (
        hashlib.sha256(original.read_bytes()).hexdigest(),
        original.stat().st_mtime_ns,
    ) == before
    with contextlib.closing(database.connect()) as conn:
        row = DerivedArtifactRepository(conn).get(aid, "proxy")
        assert row is not None and row.relpath is not None
        proxy = derived.paths.resolve(row.relpath)
        assert proxy is not None
    # Never reuse cached results against externally altered derived bytes.
    with proxy.open("ab") as stream:
        stream.write(b"changed")
    rejected = analyzer.run(params, job_id=new_id("job"))
    assert rejected["outcomes"][0]["error"]["code"] == "analysis.input_changed"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AnalysisCancelled):
        content_hash(original, cancel)
    # The same subprocess cancellation contract applies during frame decoding.
    from openworld_moments.media.process import ToolCancelled

    with pytest.raises(ToolCancelled):
        decode_frames(original, ffmpeg, cancel)


def test_analyze_api_job_and_read_events(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo
) -> None:
    output = demo(tmp_path, ProfileCatalog(), tools)
    analyzed = output["analysis"]
    assert isinstance(analyzed, dict)
    sid = analyzed["session_id"]
    database = Database.open(tmp_path / "library" / "database.sqlite3")
    derived = DerivedMedia(database, tools)
    settings = ApiSettings(
        secrets.token_hex(32), frozenset({"testserver"}), require_loopback_peer=False
    )
    engine = JobEngine(database, build_handlers(tools, database=database, derived=derived))
    with TestClient(create_app(engine, settings, derived=derived)) as client:
        assert client.get("/v1/events", params={"session_id": sid}).status_code == 401
        client.headers["Authorization"] = f"Bearer {settings.token}"
        response = client.post(
            f"/v1/sessions/{sid}/analyze",
            json={"profile_id": "generic-open-world", "idempotency_key": "analysis-once"},
        )
        assert response.status_code == 201
        job_id = response.json()["id"]
        wait_for(lambda: client.get(f"/v1/jobs/{job_id}").json()["state"] in ("ready", "failed"))
        job = client.get(f"/v1/jobs/{job_id}").json()
        assert job["state"] == "ready", job
        assert job["result"]["outcomes"][0]["status"] == "cached"
        assert (
            client.post(
                f"/v1/sessions/{sid}/analyze",
                json={"profile_id": "generic-open-world", "idempotency_key": "analysis-once"},
            ).json()["id"]
            == job_id
        )
        assert len(client.get("/v1/events", params={"session_id": sid, "limit": 1}).json()) == 1
        assert client.get("/v1/events", params={"session_id": sid, "offset": 1}).json() == []
        for invalid in (
            {"profile_id": "../elsewhere"},
            {"profile_id": "not-installed"},
            {"profile_id": "generic-open-world", "exec": "no"},
        ):
            assert client.post(f"/v1/sessions/{sid}/analyze", json=invalid).status_code == 422


def test_cli_profile_validation_and_example(tmp_path: Path, ffmpeg: ToolInfo) -> None:
    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed executable, argument array
            [sys.executable, "-m", "openworld_moments.detectors", *args],
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )

    valid = cli(
        "profiles", "validate", str(DEFAULT_CATALOG / "generic-open-world" / "profile.json")
    )
    assert valid.returncode == 0 and json.loads(valid.stdout)["valid"]
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema_version":"1.9"}')
    invalid = cli("profiles", "validate", str(broken))
    assert (
        invalid.returncode == 1 and json.loads(invalid.stdout)["error"]["code"] == "profile.invalid"
    )
    example = cli("demo")
    assert example.returncode == 0, example.stdout + example.stderr
    assert json.loads(example.stdout)["events"][0]["source"]["tool_versions"]["sdk"] == "1.0.0"
