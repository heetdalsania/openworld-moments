# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real worker subprocesses: protocol, loopback-only binding, auth, crash, and shutdown."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from tests.worker.conftest import WorkerProcess, non_loopback_address, wait_for


def test_startup_protocol_and_authenticated_health(worker_factory: Any) -> None:
    worker: WorkerProcess = worker_factory()
    ready = worker.startup
    assert ready["event"] == "ready" and ready["host"] == "127.0.0.1" and ready["port"] > 0
    assert ready["protocol"] == 1 and ready["api_version"] == 1
    status, body, headers = worker.request("GET", "/v1/health")
    assert status == 200 and body["status"] == "ok"
    assert headers["x-correlation-id"].startswith("cor_")
    assert worker.request("GET", "/v1/health", token=None)[0] == 401
    assert worker.request("GET", "/v1/health", token="0" * 64)[0] == 401
    assert worker.request("GET", "/v1/health", host="attacker.example")[0] == 403
    assert worker.stop() == 0


def test_not_reachable_through_a_non_loopback_interface(worker_factory: Any) -> None:
    address = non_loopback_address()
    if address is None:
        pytest.skip("this machine has no non-loopback IPv4 address")
    worker: WorkerProcess = worker_factory()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        assert s.connect_ex((address, worker.port)) != 0, (
            "worker accepted a connection on a LAN address"
        )


def test_refuses_to_bind_a_non_loopback_host(worker_factory: Any) -> None:
    worker: WorkerProcess = worker_factory("--host", "0.0.0.0")  # noqa: S104 - must be refused
    assert worker.startup == {
        "event": "error",
        "code": "worker.non_loopback_host",
        "message": "The worker only binds to loopback addresses.",
    }
    assert worker.proc.wait(timeout=10) == 3


def test_port_conflict_is_reported(worker_factory: Any) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        worker: WorkerProcess = worker_factory("--port", str(port))
        assert worker.startup["event"] == "error" and worker.startup["code"] == "worker.port_in_use"
        assert worker.proc.wait(timeout=10) == 3


def test_missing_token_is_reported(worker_factory: Any) -> None:
    worker: WorkerProcess = worker_factory(token="short")
    assert worker.startup["code"] == "worker.missing_token"


def test_tokens_and_environment_secrets_never_reach_logs(worker_factory: Any) -> None:
    secret_env = "env-secret-value-1234567890"
    worker: WorkerProcess = worker_factory(
        "--log-level", "debug", env={"OWM_TEST_SECRET": secret_env}
    )
    worker.request("GET", "/v1/health", token="wrong-token-abcdefghijklmnop")
    worker.request("POST", "/v1/jobs", {"kind": "diagnostic", "params": {"steps": 1, "step_ms": 0}})
    worker.stop()
    logs = worker.logs
    assert "request rejected" in logs  # logging works
    assert worker.token not in logs
    assert "wrong-token-abcdefghijklmnop" not in logs
    assert secret_env not in logs
    for line in logs.splitlines():
        json.loads(line)  # every log line is structured JSON


def test_crash_preserves_jobs_and_restart_recovers_them(
    worker_factory: Any, tmp_path: Path
) -> None:
    library = tmp_path / "library"
    first: WorkerProcess = worker_factory(library=library)
    _, job, _ = first.request(
        "POST", "/v1/jobs", {"kind": "diagnostic", "params": {"steps": 400, "step_ms": 10}}
    )
    wait_for(
        lambda: (
            first.request("GET", f"/v1/jobs/{job['id']}")[1].get("progress", {}).get("done", 0) >= 2
        )
    )
    first.kill()  # simulated crash: no shutdown hooks run

    second: WorkerProcess = worker_factory(library=library)
    recovered = wait_for(
        lambda: (j := second.request("GET", f"/v1/jobs/{job['id']}")[1])["attempt"] == 2 and j
    )
    assert recovered["id"] == job["id"]
    finished = wait_for(
        lambda: (j := second.request("GET", f"/v1/jobs/{job['id']}")[1])["state"] == "ready" and j,
        timeout=30,
    )
    assert finished["attempt"] == 2
    assert second.stop() == 0


def test_closing_stdin_shuts_the_worker_down(worker_factory: Any) -> None:
    worker: WorkerProcess = worker_factory()
    assert worker.stop(timeout=15) == 0
    assert "worker stopped" in worker.logs


def test_shutdown_endpoint_stops_the_worker(worker_factory: Any) -> None:
    worker: WorkerProcess = worker_factory()
    assert worker.request("POST", "/v1/shutdown")[0] == 202
    assert worker.proc.wait(timeout=15) == 0


def test_explicit_cache_and_rotating_log_paths_keep_canonical_data_in_library(
    worker_factory: Any, tmp_path: Path
) -> None:
    cache, logs = tmp_path / "Caches ✓", tmp_path / "Logs ✓"
    worker: WorkerProcess = worker_factory("--cache-dir", str(cache), "--log-dir", str(logs))
    assert worker.startup["event"] == "ready"
    worker.request("GET", "/v1/health", token="wrong-token-abcdefghijklmnop")
    worker.stop()
    logfile = logs / "worker.jsonl"
    assert logfile.is_file()
    text = logfile.read_text()
    assert "worker ready" in text
    assert worker.token not in text and "wrong-token-abcdefghijklmnop" not in text
    assert all(isinstance(json.loads(line), dict) for line in text.splitlines())


def test_unwritable_log_location_is_a_recoverable_startup_error(
    worker_factory: Any, tmp_path: Path
) -> None:
    invalid = tmp_path / "file-not-directory"
    invalid.write_text("preserve this")
    worker: WorkerProcess = worker_factory("--log-dir", str(invalid))
    assert worker.startup["code"] == "worker.storage_unavailable"
    assert worker.proc.wait(timeout=10) == 3
    assert invalid.read_text() == "preserve this"


def test_offline_selected_library_never_creates_an_empty_replacement(
    worker_factory: Any, tmp_path: Path
) -> None:
    missing = tmp_path / "Disconnected Drive ✓" / "library"
    worker: WorkerProcess = worker_factory("--existing-library", library=missing)
    assert worker.startup["code"] == "worker.library_unavailable"
    assert worker.proc.wait(timeout=10) == 3
    assert not missing.exists()
