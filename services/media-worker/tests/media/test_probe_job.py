# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 'probe' job through the worker API: results, failures, timeout, and cancellation."""

from __future__ import annotations

import hashlib
import secrets
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load
from openworld_moments_contracts.generated.media_asset_schema import MediaProbe

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import Database
from tests.worker.conftest import WorkerProcess, wait_for

SLOW_FFPROBE = "import time\ntime.sleep(60)\n"


class FixedTools(MediaTools):
    """MediaTools that always hands out one given ffprobe."""

    def __init__(self, ffprobe: ToolInfo) -> None:
        super().__init__()
        self._fixed = ffprobe

    def tool(self, name: str) -> ToolInfo:
        return self._fixed if name == "ffprobe" else super().tool(name)  # type: ignore[arg-type]


def _client(tmp_path: Path, tools: MediaTools, timeout_s: float = 30) -> TestClient:
    token = secrets.token_hex(32)
    database = Database.open(tmp_path / "library" / "database.sqlite3")
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    engine = JobEngine(database, build_handlers(tools, probe_timeout_s=timeout_s))
    client = TestClient(create_app(engine, settings, capabilities=tools.capabilities))
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
def api(tmp_path: Path, ffprobe: ToolInfo) -> Iterator[TestClient]:
    with _client(tmp_path, FixedTools(ffprobe)) as client:
        yield client


def _submit(client: TestClient, path: Path | str) -> str:
    response = client.post("/v1/jobs", json={"kind": "probe", "params": {"path": str(path)}})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _final(client: TestClient, job_id: str, timeout: float = 30) -> dict[str, Any]:
    def done() -> dict[str, Any] | None:
        job: dict[str, Any] = client.get(f"/v1/jobs/{job_id}").json()
        return job if job["state"] in {"ready", "failed", "cancelled"} else None

    return wait_for(done, timeout=timeout)  # type: ignore[no-any-return]


def test_probe_job_stores_a_contract_result(api: TestClient, media_dir: Path) -> None:
    source = media_dir / "hdr_pq.mp4"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    job = _final(api, _submit(api, source))
    assert job["state"] == "ready", job
    load("job", job)
    result = MediaProbe.model_validate(job["result"])
    assert result.video is not None and result.video.color.hdr is True
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest

    # The result survives a reload from SQLite (listing reads rows back).
    listed = next(j for j in api.get("/v1/jobs").json() if j["id"] == job["id"])
    assert listed["result"] == job["result"]


def test_probe_job_passes_through_probing(api: TestClient, media_dir: Path) -> None:
    states: list[str] = []
    with api.websocket_connect("/v1/jobs/events") as ws:
        job_id = _submit(api, media_dir / "h264_aac.mp4")
        while not states or states[-1] not in {"ready", "failed"}:
            event = ws.receive_json()
            if event["kind"] == "state" and event["job"]["id"] == job_id:
                states.append(event["job"]["state"])
    assert states == ["queued", "probing", "ready"]


@pytest.mark.parametrize(
    ("name", "code"),
    [("truncated.mp4", "media.damaged"), ("garbage.bin", "media.unsupported_format")],
)
def test_bad_media_fails_with_a_stable_code(
    api: TestClient, media_dir: Path, name: str, code: str
) -> None:
    job = _final(api, _submit(api, media_dir / name))
    assert job["state"] == "failed"
    error = job["error"]
    assert error["code"] == code
    assert error["retryable"] is False
    assert error["correlation_id"] == job["correlation_id"]
    assert "stderr_tail" in error and str(media_dir) not in error["stderr_tail"]
    assert str(media_dir) not in error["message"]


def test_missing_file_fails_cleanly(api: TestClient, tmp_path: Path) -> None:
    job = _final(api, _submit(api, tmp_path / "gone.mp4"))
    assert job["error"]["code"] == "media.not_found"


@pytest.mark.parametrize(
    "params",
    [{}, {"path": "relative.mp4"}, {"path": 7}, {"path": "/x.mp4", "extra": 1}],
)
def test_invalid_params_are_rejected_at_submit(api: TestClient, params: dict[str, Any]) -> None:
    response = api.post("/v1/jobs", json={"kind": "probe", "params": params})
    assert response.status_code == 422
    assert response.json()["code"] == "job.invalid_params"


def test_missing_ffprobe_is_retryable(tmp_path: Path, media_dir: Path) -> None:
    missing = ToolInfo("ffprobe", (), "path", "missing", problem="ffprobe was not found on PATH")
    with _client(tmp_path, FixedTools(missing)) as client:
        job = _final(client, _submit(client, media_dir / "h264_aac.mp4"))
    assert job["error"]["code"] == "tool.ffprobe_missing"
    assert job["error"]["retryable"] is True


def _track_spawns(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    spawned: list[subprocess.Popen[bytes]] = []

    def tracking(*args: Any, **kwargs: Any) -> Any:
        return run_tool(*args, on_spawn=spawned.append, **kwargs)

    monkeypatch.setattr("openworld_moments.media.probe.run_tool", tracking)
    return spawned


def test_cancel_terminates_ffprobe(
    tmp_path: Path,
    media_dir: Path,
    fake_tool: Callable[[str, str], ToolInfo],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned = _track_spawns(monkeypatch)
    with _client(tmp_path, FixedTools(fake_tool("slow", SLOW_FFPROBE))) as client:
        job_id = _submit(client, media_dir / "h264_aac.mp4")
        wait_for(lambda: spawned)
        assert client.post(f"/v1/jobs/{job_id}/cancel").status_code == 200
        job = _final(client, job_id, timeout=10)
    assert job["state"] == "cancelled"
    assert "error" not in job and "result" not in job
    assert spawned[0].poll() is not None, "ffprobe must be terminated and reaped"


def test_timeout_fails_retryably_and_cleans_up(
    tmp_path: Path,
    media_dir: Path,
    fake_tool: Callable[[str, str], ToolInfo],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned = _track_spawns(monkeypatch)
    tools = FixedTools(fake_tool("slow", SLOW_FFPROBE))
    with _client(tmp_path, tools, timeout_s=0.5) as client:
        job = _final(client, _submit(client, media_dir / "h264_aac.mp4"), timeout=15)
    assert job["error"]["code"] == "media.probe_timeout"
    assert job["error"]["retryable"] is True
    assert spawned[0].poll() is not None


def test_capabilities_endpoint(api: TestClient, ffprobe: ToolInfo) -> None:
    response = api.get("/v1/capabilities")
    assert response.status_code == 200
    report = response.json()
    assert report["probe_ready"] is True
    assert api.get("/v1/capabilities", params={"refresh": "true"}).status_code == 200


def test_real_worker_probes_and_reports_capabilities(
    tmp_path: Path, media_dir: Path, ffprobe: ToolInfo
) -> None:
    worker = WorkerProcess(tmp_path / "library", secrets.token_hex(32), "--ffprobe", ffprobe.path)
    try:
        assert worker.startup["event"] == "ready"
        status, capabilities, _ = worker.request("GET", "/v1/capabilities")
        assert status == 200 and capabilities["ffprobe"]["source"] == "flag"
        name = "Capture ✓ 日本語 with spaces.mp4"
        target = tmp_path / name
        target.write_bytes((media_dir / "rotated.mp4").read_bytes())
        status, job, _ = worker.request(
            "POST", "/v1/jobs", {"kind": "probe", "params": {"path": str(target)}}
        )
        assert status == 201, job

        def ready() -> dict[str, Any] | None:
            current: dict[str, Any] = worker.request("GET", f"/v1/jobs/{job['id']}")[1]
            return current if current["state"] in {"ready", "failed"} else None

        final = wait_for(ready, timeout=30)
        assert final["state"] == "ready", final
        assert final["result"]["video"]["rotation"] == 270
    finally:
        worker.stop()
    # Paths are never logged.
    assert not any(name in line or str(tmp_path) in line for line in worker.stderr_lines)


@pytest.mark.skipif(sys.platform == "win32", reason="covered by the API tests on Windows")
def test_fixture_cli(tmp_path: Path, ffmpeg: ToolInfo) -> None:
    out = tmp_path / "fx"
    from openworld_moments.media.fixtures import main

    assert main([str(out), "--ffmpeg", ffmpeg.path]) == 0
    assert (out / "manifest.json").exists() and (out / "h264_aac.mp4").stat().st_size > 0
