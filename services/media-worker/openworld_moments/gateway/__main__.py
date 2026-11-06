# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone upload gateway process (M10): ``python -m openworld_moments.gateway``.

Started by the desktop host only while its "Import from phone" screen is open.

Protocol with the host:

1. The host writes the session token (64 hex digits, 256 bits) as the first line on
   stdin and keeps stdin open. The token is never passed in arguments or the
   environment.
2. The gateway binds the one address it was given (a private LAN address; loopback
   for tests), never all interfaces, and prints one JSON line
   ``{"event": "ready", "host": ..., "port": ...}``.
3. It prints one JSON line per upload event (started, progress, done, rejected,
   interrupted) and ``{"event": "session_ended", "reason": ...}`` when the session
   expires, the phone finishes, or stdin closes; then it exits.

It shares nothing with the desktop API: no worker token, no database, no library
routes. Uploads go only to ``--staging``.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

from openworld_moments.gateway.app import Session, create_app
from openworld_moments.gateway.uploads import Limits

TOKEN_HEX = 64
DEFAULT_EXPIRES_S = 600  # spec 9.2.2: ten minutes
_emit_lock = threading.Lock()


class StartupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def emit(payload: dict[str, Any]) -> None:
    with _emit_lock:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()


def read_token(stream: Any) -> str:
    line = stream.readline()
    token = line.strip() if isinstance(line, str) else ""
    if len(token) != TOKEN_HEX or any(c not in "0123456789abcdef" for c in token):
        raise StartupError("gateway.missing_token", "Expected a 64-digit hex token on stdin.")
    return token


def check_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """A single private (or loopback) unicast address; never a wildcard or public one."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise StartupError("gateway.bad_address", f"{host!r} is not an IP address.") from exc
    if (
        address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or address.is_reserved
        or not (address.is_private or address.is_loopback)
    ):
        raise StartupError(
            "gateway.bad_address",
            "The gateway binds only to one private network address.",
        )
    return address


def bind(host: str, port: int) -> socket.socket:
    address = check_address(host)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        in_use = exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)) or (
            getattr(exc, "winerror", None) == 10048
        )
        code = "gateway.port_in_use" if in_use else "gateway.bind_failed"
        raise StartupError(code, f"Could not listen on port {port}: {exc.strerror}") from exc
    sock.listen(16)
    check_address(sock.getsockname()[0])  # belt and braces
    return sock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openworld_moments.gateway")
    parser.add_argument("--host", required=True, help="private LAN address to listen on")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--expires-s", type=int, default=DEFAULT_EXPIRES_S)
    parser.add_argument("--max-file-bytes", type=int, default=Limits.max_file_bytes)
    parser.add_argument("--max-files", type=int, default=Limits.max_files)
    parser.add_argument("--max-total-bytes", type=int, default=Limits.max_total_bytes)
    args = parser.parse_args(argv)
    try:
        if not 30 <= args.expires_s <= 3600:
            raise StartupError("gateway.bad_expiry", "Sessions last 30 seconds to 1 hour.")
        token = read_token(sys.stdin)
        sock = bind(args.host, args.port)
    except StartupError as exc:
        emit({"event": "error", "code": exc.code, "message": exc.message})
        return 2

    args.staging.mkdir(parents=True, exist_ok=True)
    port = sock.getsockname()[1]
    host_header = f"[{args.host}]:{port}" if ":" in args.host else f"{args.host}:{port}"
    server: uvicorn.Server | None = None

    def stop(_reason: str) -> None:
        if server is not None:
            server.should_exit = True

    session = Session(
        token=token,
        staging=args.staging,
        expires_at=time.monotonic() + args.expires_s,
        limits=Limits(
            max_file_bytes=args.max_file_bytes,
            max_files=args.max_files,
            max_total_bytes=args.max_total_bytes,
        ),
        allowed_hosts=frozenset({host_header}),
        emit=emit,
        on_end=stop,
    )
    config = uvicorn.Config(
        create_app(session),
        log_config=None,
        access_log=False,
        server_header=False,
        date_header=False,
        timeout_keep_alive=5,
        limit_concurrency=8,
        lifespan="off",
    )
    server = uvicorn.Server(config)

    def watch_expiry() -> None:
        while not session.finished:
            if time.monotonic() >= session.expires_at:
                session.end("expired")
                return
            time.sleep(0.5)

    def watch_stdin() -> None:
        try:
            while sys.stdin.readline():
                pass
        except (OSError, ValueError):
            pass
        session.end("closed_by_desktop")

    threading.Thread(target=watch_expiry, name="gateway-expiry", daemon=True).start()
    threading.Thread(target=watch_stdin, name="gateway-stdin", daemon=True).start()
    emit({"event": "ready", "host": args.host, "port": port, "expires_in_s": args.expires_s})
    server.run(sockets=[sock])
    session.end("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
