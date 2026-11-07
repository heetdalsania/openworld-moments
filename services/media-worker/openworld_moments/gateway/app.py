# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone upload gateway's web app (M10, spec 9.2.2).

Every route lives under ``/u/<token>/``. A wrong, expired, or finished token gets
the same plain 404 as any unknown path, so a guess learns nothing. There is no
route to the library, the desktop API, or any file other than the one being
uploaded, which is written to a fresh folder in the session's staging directory
under a sanitized name.
"""

from __future__ import annotations

import asyncio
import hmac
import html
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from openworld_moments.gateway.uploads import (
    SNIFF_BYTES,
    Limits,
    Rejected,
    check_name,
    check_size,
    sanitize_name,
    sniff,
)

#: How long a stalled upload may go without receiving data.
READ_TIMEOUT_S = 60.0
PROGRESS_EVERY_BYTES = 4 * 1024 * 1024

Emit = Callable[[dict[str, Any]], None]


@dataclass
class Upload:
    seq: int
    name: str
    size: int
    received: int = 0
    status: str = "receiving"  # receiving | received | rejected | interrupted
    reason: str | None = None

    def doc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "size": self.size,
            "received": self.received,
            "status": self.status,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass
class Session:
    token: str
    staging: Path
    expires_at: float  # time.monotonic() deadline
    limits: Limits = field(default_factory=Limits)
    allowed_hosts: frozenset[str] = frozenset()
    emit: Emit = lambda _event: None
    clock: Callable[[], float] = time.monotonic
    uploads: list[Upload] = field(default_factory=list)
    finished: bool = False
    active: int = 0
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    on_end: Callable[[str], None] = lambda _reason: None

    @property
    def live(self) -> bool:
        return not self.finished and self.clock() < self.expires_at

    def accepted_bytes(self) -> int:
        return sum(u.size for u in self.uploads if u.status in ("receiving", "received"))

    def accepted_files(self) -> int:
        return sum(1 for u in self.uploads if u.status in ("receiving", "received"))

    def end(self, reason: str) -> None:
        if not self.finished:
            self.finished = True
            self.emit({"event": "session_ended", "reason": reason})
            self.on_end(reason)


NOT_FOUND = "This upload link is not active."

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _not_found() -> Response:
    return PlainTextResponse(NOT_FOUND, status_code=404, headers=_SECURITY_HEADERS)


def _json(body: dict[str, Any], status: int = 200) -> Response:
    return JSONResponse(body, status_code=status, headers=_SECURITY_HEADERS)


def create_app(session: Session) -> Starlette:
    def authorized(request: Request) -> bool:
        token = str(request.path_params.get("token", ""))
        host = request.headers.get("host", "")
        if session.allowed_hosts and host not in session.allowed_hosts:
            return False
        return hmac.compare_digest(token.encode(), session.token.encode()) and session.live

    async def page(request: Request) -> Response:
        if not authorized(request):
            return _not_found()
        headers = {
            **_SECURITY_HEADERS,
            "Content-Security-Policy": (
                "default-src 'none'; img-src data:; "
                f"style-src 'nonce-{session.nonce}'; script-src 'nonce-{session.nonce}'; "
                "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        }
        return HTMLResponse(render_page(session), headers=headers)

    async def status(request: Request) -> Response:
        if not authorized(request):
            return _not_found()
        remaining = max(0, int(session.expires_at - session.clock()))
        return _json(
            {
                "expires_in_s": remaining,
                "files": [u.doc() for u in session.uploads],
                "limits": {
                    "max_file_bytes": session.limits.max_file_bytes,
                    "max_files": session.limits.max_files,
                },
            }
        )

    async def finish(request: Request) -> Response:
        if not authorized(request):
            return _not_found()
        session.end("finished_on_phone")
        return _json({"status": "finished"})

    async def upload(request: Request) -> Response:
        if not authorized(request):
            return _not_found()
        index = len(session.uploads) + 1
        name = sanitize_name(request.query_params.get("name"), index)
        record: Upload | None = None
        target: Path | None = None
        try:
            if session.active >= session.limits.max_concurrent:
                raise Rejected(429, "busy", "Wait for the current upload to finish.")
            check_name(name)
            length = request.headers.get("content-length")
            declared = int(length) if length and length.isdigit() else None
            try:
                free = shutil.disk_usage(session.staging).free
            except OSError:
                free = 0
            size = check_size(
                declared,
                limits=session.limits,
                accepted_files=session.accepted_files(),
                accepted_bytes=session.accepted_bytes(),
                free=free,
            )
            record = Upload(seq=index, name=name, size=size)
            session.uploads.append(record)
            session.active += 1
            folder = session.staging / f"{index:04d}"
            folder.mkdir(parents=True, exist_ok=False)
            target = folder / name
            session.emit({"event": "upload_started", "seq": index, "name": name, "size": size})
            await _receive(request, session, record, target)
        except Rejected as exc:
            if record is not None:
                record.status = "rejected"
                record.reason = exc.reason
                session.emit({"event": "upload_rejected", "seq": record.seq, "reason": exc.reason})
            else:
                session.emit({"event": "upload_refused", "name": name, "reason": exc.reason})
            _discard(target)
            return _json(
                {"status": "rejected", "reason": exc.reason, "message": exc.message}, exc.status
            )
        except (TimeoutError, ClientDisconnect):
            if record is not None:
                record.status = "interrupted"
                record.reason = "interrupted"
                session.emit({"event": "upload_interrupted", "seq": record.seq})
            _discard(target)
            return _json({"status": "interrupted"}, 400)
        finally:
            if record is not None:
                session.active -= 1
        record.status = "received"
        session.emit(
            {
                "event": "upload_done",
                "seq": record.seq,
                "name": record.name,
                "size": record.size,
                "path": f"{record.seq:04d}/{record.name}",
            }
        )
        return _json({"status": "received", "name": record.name, "size": record.size})

    async def other(_: Request) -> Response:
        return _not_found()

    routes = [
        Route("/u/{token}/", page, methods=["GET"]),
        Route("/u/{token}/status", status, methods=["GET"]),
        Route("/u/{token}/files", upload, methods=["PUT"]),
        Route("/u/{token}/finish", finish, methods=["POST"]),
        Route("/{path:path}", other, methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"]),
    ]
    return Starlette(routes=routes)


async def _receive(request: Request, session: Session, record: Upload, target: Path) -> None:
    """Stream the body to ``target`` (created exclusively), enforcing the declared size."""
    stream = request.stream().__aiter__()
    head = b""
    next_report = PROGRESS_EVERY_BYTES
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        while True:
            try:
                chunk = await asyncio.wait_for(stream.__anext__(), timeout=READ_TIMEOUT_S)
            except StopAsyncIteration:
                break
            if not chunk:
                continue
            if not session.live and not session.finished:
                raise Rejected(410, "expired", "The upload session has expired.")
            record.received += len(chunk)
            if record.received > record.size:
                raise Rejected(400, "size_mismatch", "The file is larger than announced.")
            if len(head) < SNIFF_BYTES:
                head += chunk[: SNIFF_BYTES - len(head)]
                if len(head) >= SNIFF_BYTES or record.received == record.size:
                    sniff(head, record.name)
            handle.write(chunk)
            if record.received >= next_report:
                next_report += PROGRESS_EVERY_BYTES
                session.emit(
                    {"event": "upload_progress", "seq": record.seq, "received": record.received}
                )
        if record.received != record.size:
            raise ClientDisconnect
        handle.flush()
        os.fsync(handle.fileno())


def _discard(target: Path | None) -> None:
    if target is None:
        return
    try:
        target.unlink(missing_ok=True)
        target.parent.rmdir()
    except OSError:
        pass


def render_page(session: Session) -> str:
    """The mobile upload page: inline CSS and JS under a per-session nonce."""
    nonce = html.escape(session.nonce)
    config = json.dumps(
        {
            "maxFileBytes": session.limits.max_file_bytes,
            "accept": ".mp4,.m4v,.mov,.mkv,.webm,video/*",
        }
    )
    # Script contents are not entity-decoded; the values are ours, so only "</" matters.
    return _PAGE.replace("{{NONCE}}", nonce).replace("{{CONFIG}}", config.replace("</", "<\\/"))


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Send clips to OpenWorld Moments</title>
<style nonce="{{NONCE}}">
  :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
  body { margin: 0; padding: 1.25rem; max-width: 34rem; margin-inline: auto; line-height: 1.45; }
  h1 { font-size: 1.35rem; margin: 0 0 .5rem; }
  .pick { display: block; width: 100%; padding: 1rem; font-size: 1.1rem; border-radius: 10px;
          border: 2px dashed #6b8afd; background: transparent; color: inherit; text-align: center; }
  input[type=file] { position: absolute; left: -9999px; }
  ul { list-style: none; padding: 0; }
  li { padding: .6rem 0; border-bottom: 1px solid rgba(127,127,127,.3); }
  .name { font-weight: 600; word-break: break-all; }
  progress { width: 100%; }
  .muted { opacity: .75; font-size: .9rem; }
  .bad { color: #d9480f; }
  .ok { color: #2b8a3e; }
  button.finish { margin-top: 1rem; padding: .7rem 1rem; font-size: 1rem; border-radius: 8px; }
</style>
</head>
<body>
<h1>Send clips to your computer</h1>
<p class="muted">Pick videos you downloaded (for example from the PlayStation App). They go directly
to OpenWorld Moments on your computer over this Wi-Fi network.</p>
<label class="pick" for="files">Choose videos</label>
<input id="files" type="file" multiple>
<p id="state" class="muted" role="status"></p>
<ul id="list" aria-live="polite"></ul>
<button class="finish" id="finish" type="button">I'm done</button>
<script nonce="{{NONCE}}" id="config" type="application/json">{{CONFIG}}</script>
<script nonce="{{NONCE}}">
(function () {
  var config = JSON.parse(document.getElementById("config").textContent);
  var input = document.getElementById("files");
  var list = document.getElementById("list");
  var state = document.getElementById("state");
  input.setAttribute("accept", config.accept);
  var queue = [];
  var busy = false;
  var MESSAGES = {
    unsupported_type: "Not a supported video type.",
    not_video: "This file does not look like a video.",
    too_large: "This file is too large.",
    session_full: "This session is full.",
    too_many_files: "Too many files for one session.",
    disk_full: "The computer is out of space.",
    busy: "Busy, try again.",
    expired: "The session expired."
  };
  function row(file) {
    var li = document.createElement("li");
    var name = document.createElement("div");
    name.className = "name";
    name.textContent = file.name;
    var bar = document.createElement("progress");
    bar.max = 100; bar.value = 0;
    var note = document.createElement("div");
    note.className = "muted";
    note.textContent = "Waiting";
    li.appendChild(name); li.appendChild(bar); li.appendChild(note);
    list.appendChild(li);
    return { bar: bar, note: note };
  }
  function next() {
    if (busy || queue.length === 0) return;
    busy = true;
    var item = queue.shift();
    var xhr = new XMLHttpRequest();
    xhr.open("PUT", "files?name=" + encodeURIComponent(item.file.name));
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) item.ui.bar.value = Math.round(100 * e.loaded / e.total);
      item.ui.note.textContent = "Sending";
    };
    xhr.onload = function () {
      var body = {};
      try { body = JSON.parse(xhr.responseText); } catch (e) {}
      if (xhr.status === 200) {
        item.ui.bar.value = 100;
        item.ui.note.textContent = "Received";
        item.ui.note.className = "ok";
      } else if (xhr.status === 404) {
        item.ui.note.textContent = "This link is no longer active.";
        item.ui.note.className = "bad";
      } else {
        item.ui.note.textContent = MESSAGES[body.reason] || "Not sent.";
        item.ui.note.className = "bad";
      }
      busy = false; next();
    };
    xhr.onerror = function () {
      item.ui.note.textContent = "Connection lost. Check the Wi-Fi and try again.";
      item.ui.note.className = "bad";
      busy = false; next();
    };
    xhr.send(item.file);
  }
  input.addEventListener("change", function () {
    for (var i = 0; i < input.files.length; i++) {
      var file = input.files[i];
      var ui = row(file);
      if (file.size > config.maxFileBytes) {
        ui.note.textContent = MESSAGES.too_large; ui.note.className = "bad"; continue;
      }
      queue.push({ file: file, ui: ui });
    }
    input.value = "";
    next();
  });
  document.getElementById("finish").addEventListener("click", function () {
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "finish");
    xhr.onload = function () { state.textContent = "Done. You can close this page."; };
    xhr.send();
  });
})();
</script>
</body>
</html>
"""
