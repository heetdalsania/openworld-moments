# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import BUILTIN_HANDLERS
from openworld_moments.storage import Database

WORKER_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def token() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def client(tmp_path: Path, token: str) -> Iterator[TestClient]:
    database = Database.open(tmp_path / "database.sqlite3")
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    app = create_app(JobEngine(database, BUILTIN_HANDLERS), settings)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


def wait_for(predicate: Any, timeout: float = 10.0, interval: float = 0.02) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


class WorkerProcess:
    """A real worker subprocess speaking the startup protocol."""

    def __init__(
        self, library: Path, token: str, *extra: str, env: dict[str, str] | None = None
    ) -> None:
        self.token = token
        self.proc = subprocess.Popen(  # noqa: S603 - fixed argv
            [sys.executable, "-m", "openworld_moments.worker", "--library", str(library), *extra],
            cwd=WORKER_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **(env or {})},
        )
        self.stderr_lines: list[str] = []
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        assert self.proc.stdin is not None
        self.proc.stdin.write(token + "\n")
        self.proc.stdin.flush()
        self.startup = self._read_startup()
        self.port = int(self.startup.get("port", 0))

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_lines.append(line)

    def _read_startup(self, timeout: float = 30.0) -> dict[str, Any]:
        result: list[str] = []
        stdout = self.proc.stdout
        assert stdout is not None
        reader = threading.Thread(target=lambda: result.append(stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout)
        if not result or not result[0]:
            raise AssertionError(
                f"worker gave no startup line; stderr: {''.join(self.stderr_lines)[-2000:]}"
            )
        return json.loads(result[0])  # type: ignore[no-any-return]

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        token: str | None = "default",
        host: str | None = None,
    ) -> tuple[int, Any, dict[str, str]]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method
        )
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("Authorization", f"Bearer {self.token if token == 'default' else token}")
        if host is not None:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - loopback only
                return resp.status, json.loads(resp.read() or b"null"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null"), dict(exc.headers)

    def stop(self, timeout: float = 15.0) -> int:
        if self.proc.poll() is None and self.proc.stdin is not None:
            self.proc.stdin.close()  # EOF tells the worker to shut down
        return self.proc.wait(timeout=timeout)

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=10)

    @property
    def logs(self) -> str:
        return "".join(self.stderr_lines)


@pytest.fixture
def worker_factory(tmp_path: Path) -> Iterator[Any]:
    started: list[WorkerProcess] = []

    def start(
        *extra: str,
        token: str | None = None,
        library: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerProcess:
        proc = WorkerProcess(
            library or tmp_path / "library", token or secrets.token_hex(32), *extra, env=env
        )
        started.append(proc)
        return proc

    yield start
    for proc in started:
        if proc.proc.poll() is None:
            proc.kill()


def non_loopback_address() -> str | None:
    """An address of this machine that is not loopback, if any."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1; no packets are sent for UDP connect
            address = str(s.getsockname()[0])
        except OSError:
            return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address  # noqa: S104
