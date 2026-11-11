# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone upload gateway (M10): threat-focused tests for tokens, expiry, filenames,
limits, content checks, interrupted and duplicate uploads, and the real process."""

from __future__ import annotations

import asyncio
import http.client
import json
import secrets
import shutil
import subprocess
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from openworld_moments.gateway.app import NOT_FOUND, Session, create_app
from openworld_moments.gateway.uploads import (
    Limits,
    Rejected,
    check_name,
    check_size,
    sanitize_name,
)

TOKEN = "a" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200  # starts like an MP4
MKV = b"\x1a\x45\xdf\xa3" + b"\x00" * 200


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def session(tmp_path: Path, events: list[dict[str, Any]], clock: Clock) -> Session:
    staging = tmp_path / "staging"
    staging.mkdir()
    return Session(
        token=TOKEN,
        staging=staging,
        expires_at=clock.now + 600,
        limits=Limits(
            max_file_bytes=1024 * 1024,
            max_files=3,
            max_total_bytes=2 * 1024 * 1024,
            free_space_margin=0,
        ),
        emit=events.append,
        clock=clock,
    )


@pytest.fixture
def client(session: Session) -> TestClient:
    return TestClient(create_app(session))


def put(client: TestClient, name: str, body: bytes, token: str = TOKEN) -> Any:
    return client.put(f"/u/{token}/files", params={"name": name}, content=body)


def staged(session: Session) -> list[Path]:
    return sorted(p for p in session.staging.rglob("*") if p.is_file())


# -- filenames and limits -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Heist finale.mp4", "Heist finale.mp4"),
        ("../../etc/passwd.mp4", "passwd.mp4"),
        ("..\\..\\Windows\\win.mov", "win.mov"),
        ("C:\\Users\\me\\clip.MP4", "clip.MP4"),
        ("/absolute/path/clip.mkv", "clip.mkv"),
        ("CON.mp4", "_CON.mp4"),
        ("lpt1.mov", "_lpt1.mov"),
        ("...hidden.mp4", "hidden.mp4"),
        ("a\x00b\x1fc.mp4", "a_b_c.mp4"),
        ('in<va>l:i"d|?*.webm', "in_va_l_i_d___.webm"),
        ("", "clip-0007"),
        ("..", "clip-0007"),
        (".mp4", "clip-0007.mp4"),
    ],
)
def test_names_are_reduced_to_one_safe_component(raw: str, expected: str) -> None:
    name = sanitize_name(raw, 7)
    assert name == expected
    assert "/" not in name and "\\" not in name and name not in ("", ".", "..")


def test_long_names_keep_their_extension() -> None:
    name = sanitize_name("x" * 500 + ".mp4", 1)
    assert len(name) <= 120 and name.endswith(".mp4")


def test_only_video_extensions_are_allowed() -> None:
    for ok in ("a.mp4", "a.MOV", "a.m4v", "a.mkv", "a.webm"):
        check_name(ok)
    for bad in ("a.exe", "a.mp4.exe", "a.html", "a.svg", "mp4", "a.jpg", "clip-0001"):
        with pytest.raises(Rejected) as caught:
            check_name(bad)
        assert caught.value.status == 415


def test_size_rules() -> None:
    limits = Limits(max_file_bytes=100, max_files=2, max_total_bytes=150, free_space_margin=10)
    args: dict[str, Any] = {
        "limits": limits,
        "accepted_files": 0,
        "accepted_bytes": 0,
        "free": 1000,
    }
    assert check_size(50, **args) == 50
    for declared, overrides, status in (
        (None, {}, 411),
        (0, {}, 400),
        (101, {}, 413),
        (50, {"accepted_files": 2}, 413),
        (60, {"accepted_bytes": 100}, 413),
        (50, {"free": 55}, 507),
    ):
        with pytest.raises(Rejected) as caught:
            check_size(declared, **{**args, **overrides})
        assert caught.value.status == status


# -- tokens, expiry, routes -----------------------------------------------------------


def test_wrong_tokens_and_unknown_paths_look_the_same(client: TestClient) -> None:
    responses = [
        client.get(f"/u/{'b' * 64}/"),
        client.get("/u/short/"),
        client.get("/"),
        client.get("/v1/assets"),
        client.get("/v1/health"),
        client.get(f"/u/{TOKEN}/../../etc/passwd"),
        put(client, "a.mp4", MP4, token="b" * 64),
        client.post(f"/u/{'b' * 64}/finish"),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.text == NOT_FOUND
    assert client.get(f"/u/{TOKEN}/").status_code == 200


def test_expired_and_finished_sessions_refuse_everything(
    client: TestClient, session: Session, clock: Clock, events: list[dict[str, Any]]
) -> None:
    clock.now += 601
    for response in (client.get(f"/u/{TOKEN}/"), put(client, "a.mp4", MP4)):
        assert response.status_code == 404 and response.text == NOT_FOUND
    assert staged(session) == []
    clock.now -= 601
    assert client.post(f"/u/{TOKEN}/finish").status_code == 200
    assert {"event": "session_ended", "reason": "finished_on_phone"} in events
    assert client.get(f"/u/{TOKEN}/status").status_code == 404


def test_other_hosts_are_refused(session: Session) -> None:
    session.allowed_hosts = frozenset({"192.168.1.20:5555"})
    client = TestClient(create_app(session))
    assert client.get(f"/u/{TOKEN}/").status_code == 404  # Host: testserver
    good = client.get(f"/u/{TOKEN}/", headers={"host": "192.168.1.20:5555"})
    assert good.status_code == 200


def test_page_is_locked_down(client: TestClient, session: Session) -> None:
    response = client.get(f"/u/{TOKEN}/")
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and f"'nonce-{session.nonce}'" in csp
    assert response.headers["referrer-policy"] == "no-referrer"  # the token is in the URL
    assert response.headers["cache-control"] == "no-store"
    assert "<script nonce=" in response.text and "eval(" not in response.text
    status = client.get(f"/u/{TOKEN}/status").json()
    assert status["files"] == [] and 0 < status["expires_in_s"] <= 600
    assert str(session.staging) not in client.get(f"/u/{TOKEN}/status").text


# -- uploads --------------------------------------------------------------------------


def test_upload_lands_only_in_staging(
    client: TestClient, session: Session, events: list[dict[str, Any]]
) -> None:
    response = put(client, "../../../evil/../Heist finale.mp4", MP4)
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "received", "name": "Heist finale.mp4", "size": len(MP4)}
    files = staged(session)
    assert files == [session.staging / "0001" / "Heist finale.mp4"]
    assert files[0].read_bytes() == MP4
    assert files[0].resolve().is_relative_to(session.staging.resolve())
    done = [e for e in events if e["event"] == "upload_done"]
    assert done == [
        {
            "event": "upload_done",
            "seq": 1,
            "name": "Heist finale.mp4",
            "size": len(MP4),
            "path": "0001/Heist finale.mp4",
        }
    ]
    status = client.get(f"/u/{TOKEN}/status").json()
    assert status["files"][0]["status"] == "received"


def test_duplicate_uploads_get_separate_folders(client: TestClient, session: Session) -> None:
    assert put(client, "clip.mp4", MP4).status_code == 200
    assert put(client, "clip.mp4", MP4).status_code == 200
    assert [p.relative_to(session.staging).as_posix() for p in staged(session)] == [
        "0001/clip.mp4",
        "0002/clip.mp4",
    ]


def test_upload_after_staging_folder_was_tidied(client: TestClient, session: Session) -> None:
    # The desktop deletes each imported copy; a removed session folder must not be
    # reported to the phone as a full disk (Windows client qualification, M10).
    assert put(client, "first.mp4", MP4).status_code == 200
    shutil.rmtree(session.staging)
    response = put(client, "second.mp4", MP4)
    assert response.status_code == 200, response.text
    assert staged(session) == [session.staging / "0002" / "second.mp4"]


def test_unavailable_storage_is_not_reported_as_full(client: TestClient, session: Session) -> None:
    session.staging.rmdir()
    session.staging.write_bytes(b"")  # a file where the folder should be
    response = put(client, "clip.mp4", MP4)
    assert response.status_code == 500
    assert response.json()["reason"] == "storage_unavailable"


def test_unsupported_and_disguised_files_never_stay(
    client: TestClient, session: Session, events: list[dict[str, Any]]
) -> None:
    exe = put(client, "setup.exe", b"MZ" + b"\x00" * 100)
    assert exe.status_code == 415 and exe.json()["reason"] == "unsupported_type"
    disguised = put(client, "clip.mp4", b"<html><script>alert(1)</script></html>")
    assert disguised.status_code == 415 and disguised.json()["reason"] == "not_video"
    wrong_family = put(client, "clip.webm", MP4)
    assert wrong_family.status_code == 415
    assert put(client, "real.mkv", MKV).status_code == 200
    assert [p.name for p in staged(session)] == ["real.mkv"]
    assert not any(p.is_dir() and not any(p.iterdir()) for p in session.staging.iterdir())
    assert any(e["event"] == "upload_rejected" and e["reason"] == "not_video" for e in events)


def test_oversized_and_over_limit_uploads_are_refused_before_writing(
    client: TestClient, session: Session
) -> None:
    big = put(client, "big.mp4", MP4 + b"\x00" * (1024 * 1024))
    assert big.status_code == 413 and big.json()["reason"] == "too_large"
    assert staged(session) == []
    for _ in range(3):
        assert put(client, "c.mp4", MP4).status_code == 200
    full = put(client, "d.mp4", MP4)
    assert full.status_code == 413 and full.json()["reason"] == "too_many_files"
    assert len(staged(session)) == 3


def test_concurrent_upload_limit(client: TestClient, session: Session) -> None:
    session.active = session.limits.max_concurrent
    busy = put(client, "a.mp4", MP4)
    assert busy.status_code == 429 and busy.json()["reason"] == "busy"


async def _raw_put(
    session: Session, declared: int, chunks: list[bytes], *, disconnect: bool
) -> tuple[int, list[MutableMapping[str, Any]]]:
    """Drive the ASGI app directly to simulate a phone that stops mid-upload or lies."""
    app = create_app(session)
    messages = [{"type": "http.request", "body": c, "more_body": True} for c in chunks]
    if disconnect:
        messages.append({"type": "http.disconnect"})
    else:
        messages.append({"type": "http.request", "body": b"", "more_body": False})
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": f"/u/{TOKEN}/files",
        "raw_path": f"/u/{TOKEN}/files".encode(),
        "query_string": b"name=clip.mp4",
        "headers": [(b"host", b"testserver"), (b"content-length", str(declared).encode())],
        "client": ("192.168.1.30", 50000),
        "server": ("192.168.1.20", 5555),
    }
    await app(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), 0)
    return status, sent


def test_interrupted_upload_leaves_nothing(session: Session, events: list[dict[str, Any]]) -> None:
    status, _ = asyncio.run(_raw_put(session, 10_000, [MP4[:100]], disconnect=True))
    assert staged(session) == []
    assert any(e["event"] == "upload_interrupted" for e in events)
    assert session.uploads[0].status == "interrupted"
    assert status in (0, 400)  # nobody is listening after a disconnect


def test_short_body_counts_as_interrupted(session: Session) -> None:
    status, _ = asyncio.run(_raw_put(session, 10_000, [MP4], disconnect=False))
    assert status == 400 and staged(session) == []


def test_body_larger_than_announced_is_refused(session: Session) -> None:
    status, _ = asyncio.run(_raw_put(session, 50, [MP4, MP4], disconnect=False))
    assert status == 400 and staged(session) == []
    assert session.uploads[0].reason == "size_mismatch"


def test_upload_after_expiry_mid_stream_is_discarded(session: Session, clock: Clock) -> None:
    async def run() -> int:
        clock.now += 601  # the session expires while bytes are arriving
        status, _ = await _raw_put(session, len(MP4) * 2, [MP4, MP4], disconnect=False)
        return status

    assert asyncio.run(run()) == 404 or staged(session) == []
    assert staged(session) == []


# -- the real process -----------------------------------------------------------------


def _start(tmp_path: Path, *args: str, token: str | None = None) -> subprocess.Popen[str]:
    proc = subprocess.Popen(  # noqa: S603 - fixed argument list
        [
            sys.executable,
            "-m",
            "openworld_moments.gateway",
            "--staging",
            str(tmp_path / "staging"),
            *args,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write((token if token is not None else secrets.token_hex(32)) + "\n")
    proc.stdin.flush()
    return proc


def _event(proc: subprocess.Popen[str]) -> dict[str, Any]:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, "gateway exited without output"
    event: dict[str, Any] = json.loads(line)
    return event


def test_process_serves_only_while_active(tmp_path: Path) -> None:
    token = secrets.token_hex(32)
    proc = _start(tmp_path, "--host", "127.0.0.1", token=token)
    try:
        ready = _event(proc)
        assert ready["event"] == "ready" and ready["host"] == "127.0.0.1"
        port = ready["port"]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("PUT", f"/u/{token}/files?name=phone%20clip.mp4", body=MP4)
        response = conn.getresponse()
        assert response.status == 200, response.read()
        response.read()
        assert _event(proc)["event"] == "upload_started"
        assert _event(proc)["event"] == "upload_done"
        conn.request("GET", "/v1/assets")
        assert conn.getresponse().status == 404
        conn.close()
        assert proc.stdin is not None
        proc.stdin.close()  # the desktop closed the screen
        assert _event(proc) == {"event": "session_ended", "reason": "closed_by_desktop"}
        assert proc.wait(timeout=15) == 0
        with pytest.raises(OSError):
            http.client.HTTPConnection("127.0.0.1", port, timeout=3).request("GET", "/")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert (tmp_path / "staging" / "0001" / "phone clip.mp4").read_bytes() == MP4


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "8.8.8.8", "224.0.0.1", "169.254.1.1", "nope"])  # noqa: S104 - checks the refusal
def test_process_refuses_wildcard_public_and_odd_addresses(tmp_path: Path, host: str) -> None:
    proc = _start(tmp_path, "--host", host)
    event = _event(proc)
    assert event["event"] == "error" and event["code"] == "gateway.bad_address"
    assert proc.wait(timeout=10) == 2


def test_process_requires_a_strong_token(tmp_path: Path) -> None:
    proc = _start(tmp_path, "--host", "127.0.0.1", token="short")
    event = _event(proc)
    assert event == {
        "event": "error",
        "code": "gateway.missing_token",
        "message": "Expected a 64-digit hex token on stdin.",
    }
    assert proc.wait(timeout=10) == 2


def test_process_honours_a_chosen_port_and_reports_a_busy_one(tmp_path: Path) -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    proc = _start(tmp_path, "--host", "127.0.0.1", "--port", str(free_port))
    try:
        assert _event(proc)["port"] == free_port
        busy = _start(tmp_path / "second", "--host", "127.0.0.1", "--port", str(free_port))
        event = _event(busy)
        assert event["event"] == "error" and event["code"] == "gateway.port_in_use"
        assert busy.wait(timeout=10) == 2
    finally:
        proc.kill()
        proc.wait()


def test_process_expires_on_its_own(tmp_path: Path) -> None:
    proc = _start(tmp_path, "--host", "127.0.0.1", "--expires-s", "30")
    try:
        assert _event(proc)["event"] == "ready"
    finally:
        proc.kill()
        proc.wait()
    proc = _start(tmp_path, "--host", "127.0.0.1", "--expires-s", "5")
    event = _event(proc)
    assert event["event"] == "error" and event["code"] == "gateway.bad_expiry"
    proc.wait(timeout=10)
