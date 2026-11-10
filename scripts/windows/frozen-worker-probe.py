# SPDX-License-Identifier: AGPL-3.0-or-later
"""Probe a worker build outside the desktop host (M29 CI diagnostics).

Launches the worker exactly as the host does (token on stdin, stdin kept open),
then for a few seconds makes the requests the UI makes after startup: health,
jobs, system doctor, model manager and the job-event WebSocket (as the host opens it).
If the process exits, prints its exit code and its own stderr, which the native
WebView smoke cannot see. Uses a new scratch library only.

    python scripts/windows/frozen-worker-probe.py <worker.exe> [args...]
    python scripts/windows/frozen-worker-probe.py python -m openworld_moments.worker
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "packaging"
PATHS = ("/v1/health", "/v1/jobs?limit=200", "/v1/system-doctor", "/v1/model-manager")
SECONDS = 15.0


def websocket_upgrade(port: int, token: str) -> str:
    key = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(
            (
                f"GET /v1/jobs/events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                f"Authorization: Bearer {token}\r\n\r\n"
            ).encode()
        )
        return sock.recv(200).decode("latin-1").split("\r\n", 1)[0]


def main() -> int:
    command = sys.argv[1:]
    if not command:
        print(__doc__, file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    library = Path(tempfile.mkdtemp(prefix="owm-probe-")) / "library"
    token = secrets.token_hex(32)
    proc = subprocess.Popen(  # noqa: S603 - the CI-built worker, fixed arguments
        [*command, "--library", str(library)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stderr: list[str] = []
    threading.Thread(
        target=lambda: stderr.extend(iter(proc.stderr.readline, "")),  # type: ignore[union-attr]
        daemon=True,
    ).start()
    if proc.stdin is None or proc.stdout is None:  # pragma: no cover - both are PIPE
        raise RuntimeError("worker pipes unavailable")
    proc.stdin.write(token + "\n")
    proc.stdin.flush()
    report: dict[str, object] = {"command": [Path(command[0]).name, *command[1:]], "requests": []}
    startup = proc.stdout.readline()
    report["startup"] = startup.strip()
    requests: list[dict[str, object]] = report["requests"]  # type: ignore[assignment]
    try:
        port = int(json.loads(startup)["port"])
    except (ValueError, KeyError, TypeError):
        port = 0
    deadline = time.monotonic() + SECONDS
    while port and time.monotonic() < deadline and proc.poll() is None:
        for path in PATHS:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}", headers={"Authorization": f"Bearer {token}"}
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback
                    requests.append({"path": path, "status": response.status})
            except urllib.error.HTTPError as error:
                requests.append({"path": path, "status": error.code})
            except OSError as error:
                requests.append({"path": path, "error": str(error)[:300]})
        try:
            line = websocket_upgrade(port, token)
            requests.append({"path": "/v1/jobs/events (upgrade)", "status_line": line})
        except OSError as error:
            requests.append({"path": "/v1/jobs/events (upgrade)", "error": str(error)[:300]})
        time.sleep(1)
    alive = proc.poll() is None
    report["alive_after_probe"] = alive
    if alive:
        proc.stdin.close()  # the host's shutdown signal
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    time.sleep(0.5)  # let the stderr reader finish
    report["exit_code"] = proc.returncode
    report["stderr_tail"] = "".join(stderr)[-6000:].replace(token, "<token>")
    # Keep only the first and last few request results in the report.
    report["requests"] = requests[:12] + (["…"] if len(requests) > 24 else []) + requests[-12:]
    (OUT / "frozen-worker-probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "requests"}, indent=2))
    if not alive or not port:
        print("The worker exited during the probe; see stderr_tail above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
