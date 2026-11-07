# SPDX-License-Identifier: AGPL-3.0-or-later
"""Worker process: startup protocol, loopback binding, and lifecycle.

Protocol with the desktop host (docs/architecture/worker.md):

1. The host starts ``python -m openworld_moments.worker --library DIR`` and
   writes the per-launch token as the first line on stdin. It keeps stdin open.
2. The worker binds 127.0.0.1 on an ephemeral port (or ``--port``), opens and
   migrates the library database, starts the job engine, and prints exactly one
   JSON line on stdout: ``{"event": "ready", "port": ..., ...}`` or
   ``{"event": "error", "code": ..., "message": ...}`` followed by exit code 3.
3. When stdin reaches EOF (the host exited or asked it to), the worker shuts down.

stdout carries only these protocol lines; logs go to stderr as JSON.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import logging
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any

import uvicorn
from openworld_moments_contracts.versioning import SUPPORTED_VERSION

from openworld_moments import __version__
from openworld_moments.api.app import API_VERSION, ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.ingest.library import LibraryPaths
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.logs import configure_logging
from openworld_moments.media.tools import MediaTools
from openworld_moments.redaction import Redactor
from openworld_moments.storage import Database, StorageError
from openworld_moments.transcripts.service import Transcriber

PROTOCOL_VERSION = 1
EXIT_STARTUP_FAILED = 3
MIN_TOKEN_LENGTH = 32
log = logging.getLogger("openworld_moments.worker")


class StartupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def read_token(stream: Any) -> str:
    line = stream.readline()
    token = line.strip() if isinstance(line, str) else ""
    if len(token) < MIN_TOKEN_LENGTH or not token.isascii() or not token.isalnum():
        raise StartupError(
            "worker.missing_token", "Expected a token of at least 32 letters or digits on stdin."
        )
    return token


def bind_loopback(host: str, port: int) -> socket.socket:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise StartupError("worker.non_loopback_host", f"{host!r} is not an IP address") from exc
    if not address.is_loopback:
        raise StartupError(
            "worker.non_loopback_host", "The worker only binds to loopback addresses."
        )
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform == "win32":  # refuse to share the port with another process
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        if (
            exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1))
            or getattr(exc, "winerror", None) == 10048
        ):
            raise StartupError("worker.port_in_use", f"Port {port} is already in use.") from exc
        raise StartupError(
            "worker.bind_failed", f"Could not bind {host}:{port}: {exc.strerror}"
        ) from exc
    sock.listen(128)
    bound = ipaddress.ip_address(sock.getsockname()[0])
    if not bound.is_loopback:  # belt and braces: never serve on another interface
        sock.close()
        raise StartupError("worker.non_loopback_host", "Bound address is not loopback.")
    return sock


def watch_stdin(on_eof: Any) -> None:
    def run() -> None:
        try:
            while sys.stdin.readline():
                pass
        except (OSError, ValueError):
            pass
        on_eof()

    threading.Thread(target=run, name="stdin-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openworld_moments.worker")
    parser.add_argument(
        "--library", type=Path, required=True, help="library folder (holds database.sqlite3)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument(
        "--log-level", default="info", choices=["debug", "info", "warning", "error"]
    )
    parser.add_argument("--ffprobe", help="ffprobe executable (default: OWM_FFPROBE, then PATH)")
    parser.add_argument("--ffmpeg", help="ffmpeg executable (default: OWM_FFMPEG, then PATH)")
    args = parser.parse_args(argv)

    redactor = Redactor()
    configure_logging(redactor, level=getattr(logging, args.log_level.upper()))
    try:
        token = read_token(sys.stdin)
        redactor.add_secret(token)
        sock = bind_loopback(args.host, args.port)
        database = Database.open(args.library / "database.sqlite3")
    except StartupError as exc:
        emit({"event": "error", "code": exc.code, "message": exc.message})
        return EXIT_STARTUP_FAILED
    except StorageError as exc:
        emit({"event": "error", "code": "worker.database_error", "message": redactor(str(exc))})
        return EXIT_STARTUP_FAILED

    host, port = sock.getsockname()[:2]
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    server: uvicorn.Server | None = None

    def request_shutdown() -> None:
        if server is not None:
            server.should_exit = True

    def on_ready() -> None:
        emit(
            {
                "event": "ready",
                "protocol": PROTOCOL_VERSION,
                "api_version": API_VERSION,
                "schema_version": str(SUPPORTED_VERSION),
                "worker_version": __version__,
                "host": host,
                "port": port,
                "pid": os.getpid(),
            }
        )
        log.info("worker ready", extra={"port": port})

    settings = ApiSettings(
        token=token,
        allowed_hosts=frozenset({authority, f"localhost:{port}"}),
        on_shutdown_request=request_shutdown,
    )
    tools = MediaTools(ffprobe=args.ffprobe, ffmpeg=args.ffmpeg)
    # No job runs yet, so every staging leftover is from a crash: remove it.
    LibraryPaths.for_database(database.path).clean_import_staging()
    derived = DerivedMedia(database, tools)
    derived.paths.clean_staging()
    transcriber = Transcriber(database, tools, derived)
    transcriber.clean_staging()
    app = create_app(
        JobEngine(
            database,
            build_handlers(tools, database=database, derived=derived, transcriber=transcriber),
        ),
        settings,
        on_ready=on_ready,
        capabilities=tools.capabilities,
        derived=derived,
        transcriber=transcriber,
    )
    config = uvicorn.Config(
        app,
        log_config=None,
        access_log=False,
        lifespan="on",
        ws="websockets-sansio",
        server_header=False,
    )
    server = uvicorn.Server(config)
    watch_stdin(request_shutdown)
    server.run(sockets=[sock])
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
