# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import hashlib
import io
import json
import shutil
import threading
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.jobs.engine import Cancelled
from openworld_moments.transcripts.catalog import DATA, Catalog, read_catalog
from openworld_moments.transcripts.downloads import Downloads, checked_url
from openworld_moments.transcripts.whisper import TranscriptionError, sha256_file

CONTENT = b"ggml" + b"x" * 4092
DIGEST = hashlib.sha256(CONTENT).hexdigest()


class Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200, content_range: str | None = None):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Range": content_range} if content_range else {}


@pytest.fixture
def manager(tmp_path: Path) -> Downloads:
    library = tmp_path / "Library ✓ 日本語"
    library.mkdir()
    model = read_catalog().models[0].model_dump()
    model.update(size_bytes=len(CONTENT), sha256=DIGEST)
    catalog = Catalog.model_validate({"version": 1, "models": [model]})
    return Downloads(library, catalog=catalog, opener=lambda _url, _offset: Response(CONTENT))


def progress(_done: int, _total: int, _message: str) -> None:
    pass


def test_bundled_signature_and_tampering() -> None:
    catalog = read_catalog()
    assert len(catalog.models) == 2
    raw = (DATA / "models.json").read_bytes()
    signature = (DATA / "models.sig").read_bytes()
    for data, sig in [(raw + b" ", signature), (raw, b"invalid"), (b"x" * 65537, signature)]:
        with pytest.raises(TranscriptionError, match="signed model catalog"):
            read_catalog(data, sig)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model",
        "http://huggingface.co/a",
        "https://127.0.0.1/x",
        "https://evil.example/a",
        "https://u:p@huggingface.co/a",
        "https://huggingface.co:444/a",
    ],
)
def test_download_origin_refused(url: str) -> None:
    with pytest.raises(TranscriptionError):
        checked_url(url)


def test_verified_install_pin_removal_and_source_preservation(manager: Downloads) -> None:
    media = manager.library / "source.mp4"
    media.write_bytes(b"source media sentinel")
    before = (media.read_bytes(), media.stat().st_mtime_ns)
    manager.run("tiny.en", threading.Event(), progress)
    assert manager.models.get("tiny.en").sha256 == DIGEST
    load("model-manager", manager.status())
    assert manager.status()["models"][0]["active_sha256"] == DIGEST
    manager.change("tiny.en", DIGEST)
    manager.change("tiny.en", None)
    assert not manager.models.installed()
    assert manager.status()["models"][0]["versions"] == []
    assert (media.read_bytes(), media.stat().st_mtime_ns) == before


def test_interrupted_download_resumes_exact_range(manager: Downloads) -> None:
    manager.opener = lambda _url, _offset: Response(CONTENT[:2000])
    with pytest.raises(TranscriptionError, match="interrupted"):
        manager.run("tiny.en", threading.Event(), progress)
    assert not manager.models.installed()
    assert manager.status()["models"][0]["downloaded_bytes"] == 2000
    offsets = []

    def resume(_url: str, offset: int) -> Response:
        offsets.append(offset)
        return Response(CONTENT[offset:], 206, f"bytes {offset}-4095/4096")

    manager.opener = resume
    manager.run("tiny.en", threading.Event(), progress)
    assert offsets == [2000]
    assert manager.models.get("tiny.en").sha256 == DIGEST


def test_ignored_range_restarts_instead_of_appending(manager: Downloads) -> None:
    (manager.directory("downloads") / f"tiny.en-{DIGEST}.part").write_bytes(CONTENT[:1000])
    manager.run("tiny.en", threading.Event(), progress)
    assert manager.models.get("tiny.en").path.read_bytes() == CONTENT


@pytest.mark.parametrize(
    "response",
    [
        Response(CONTENT, 206, "bytes 1-4095/4096"),
        Response(b"bad!" + CONTENT[4:]),
        Response(CONTENT + b"overflow"),
    ],
)
def test_corruption_oversize_and_wrong_ranges_never_install(
    manager: Downloads, response: Response
) -> None:
    manager.opener = lambda _url, _offset: response
    with pytest.raises(TranscriptionError):
        manager.run("tiny.en", threading.Event(), progress)
    assert not manager.models.installed()
    assert not manager.status()["models"][0]["active_sha256"]


def test_same_size_corruption_is_not_reported_installed(manager: Downloads) -> None:
    manager.run("tiny.en", threading.Event(), progress)
    manager.models.get("tiny.en").path.write_bytes(b"bad!" + CONTENT[4:])
    assert not manager.models.installed()
    assert not manager.status()["models"][0]["active_sha256"]


def test_cancel_keeps_resumable_bytes_but_never_activates(manager: Downloads) -> None:
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        manager.run("tiny.en", cancel, lambda *_: cancel.set())
    assert not manager.models.installed()
    assert manager.status()["models"][0]["downloaded_bytes"] == len(CONTENT)
    manager.opener = lambda *_: pytest.fail("full verified partial should not download again")
    manager.run("tiny.en", threading.Event(), progress)
    assert manager.models.get("tiny.en").sha256 == DIGEST


def test_low_disk_and_offline_preserve_active_model(manager: Downloads, monkeypatch: Any) -> None:
    manager.run("tiny.en", threading.Event(), progress)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 100, 0))
    with pytest.raises(TranscriptionError) as error:
        manager.run("tiny.en", threading.Event(), progress)
    assert error.value.code == "models.disk_full"
    monkeypatch.undo()

    def offline(*_: Any) -> Response:
        raise urllib.error.URLError("offline")

    manager.opener = offline
    with pytest.raises(TranscriptionError) as error:
        manager.run("tiny.en", threading.Event(), progress)
    assert error.value.code == "models.offline"
    assert manager.models.get("tiny.en").sha256 == DIGEST


def test_linked_partial_cannot_mutate_source(manager: Downloads) -> None:
    source = manager.library / "source.bin"
    source.write_bytes(CONTENT)
    link = manager.directory("downloads") / f"tiny.en-{DIGEST}.part"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Creating a symlink requires Windows privileges")
    with pytest.raises(TranscriptionError):
        manager.run("tiny.en", threading.Event(), progress)
    assert source.read_bytes() == CONTENT


def test_shared_lock_rejects_concurrent_removal(manager: Downloads) -> None:
    other = Downloads(manager.library, catalog=manager.catalog)
    with manager.exclusive(), pytest.raises(TranscriptionError) as error:
        other.change("tiny.en", None)
    assert error.value.code == "models.busy"


def test_bad_receipt_does_not_become_a_version(manager: Downloads) -> None:
    p = manager.directory("versions") / f"tiny.en-{DIGEST}.json"
    p.write_text(json.dumps({"sha256": "../escape"}))
    assert not manager.status()["models"][0]["versions"]


def test_authenticated_api_and_durable_job_use_same_model_store(manager: Downloads) -> None:
    from fastapi.testclient import TestClient

    from openworld_moments.api.app import ApiSettings, create_app
    from openworld_moments.jobs.engine import JobEngine
    from openworld_moments.jobs.handlers import build_handlers
    from openworld_moments.media.tools import MediaTools
    from openworld_moments.storage import Database
    from tests.worker.conftest import wait_for

    database = Database.open(manager.library / "database.sqlite3")
    engine = JobEngine(database, build_handlers(MediaTools(), database=database, downloads=manager))
    app = create_app(
        engine,
        ApiSettings(
            token="a" * 64, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
        ),
        downloads=manager,
    )
    with TestClient(app) as client:
        assert client.get("/v1/model-manager").status_code == 401
        client.headers["Authorization"] = "Bearer " + "a" * 64
        assert (
            client.post("/v1/model-manager/download", json={"name": "../../escape"}).status_code
            == 422
        )
        job = client.post("/v1/model-manager/download", json={"name": "tiny.en"})
        assert job.status_code == 201
        assert job.json()["params"]["sha256"] == DIGEST
        job_id = job.json()["id"]
        result = wait_for(
            lambda: (
                j
                if (j := client.get(f"/v1/jobs/{job_id}").json())["state"] in {"ready", "failed"}
                else None
            )
        )
        assert result["state"] == "ready", result
        assert client.get("/v1/model-manager").json()["models"][0]["active_sha256"] == DIGEST
        assert (
            client.post(
                "/v1/model-manager/pin", json={"name": "tiny.en", "sha256": DIGEST}
            ).status_code
            == 200
        )
        assert client.post("/v1/model-manager/remove", json={"name": "tiny.en"}).status_code == 200
        assert not manager.models.installed()


def test_real_http_interruption_and_range_resume(manager: Downloads, monkeypatch: Any) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from openworld_moments.transcripts import downloads

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:
            offset = int(self.headers["Range"].removeprefix("bytes=").removesuffix("-"))
            requests.append(offset)
            self.send_response(206 if offset else 200)
            if offset:
                self.send_header("Content-Range", f"bytes {offset}-4095/4096")
            self.send_header("Content-Length", str(len(CONTENT) - offset))
            self.end_headers()
            self.wfile.write(CONTENT[offset:] if offset else CONTENT[:2000])
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/model"
    check = downloads.checked_url

    def test_origin(value: str) -> None:
        if value != url:
            check(value)

    monkeypatch.setattr(downloads, "checked_url", test_origin)
    manager.opener = lambda _url, offset: downloads.open_download(url, offset)
    try:
        with pytest.raises(TranscriptionError):
            manager.run("tiny.en", threading.Event(), progress)
        manager.run("tiny.en", threading.Event(), progress)
        assert requests == [0, 2000]
        assert manager.models.get("tiny.en").sha256 == DIGEST
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cancellation_during_verification_does_not_activate(
    manager: Downloads, monkeypatch: Any
) -> None:
    from openworld_moments.transcripts import downloads

    cancel = threading.Event()
    original = sha256_file

    def interrupted(path: Path) -> str:
        result = original(path)
        cancel.set()
        return result

    monkeypatch.setattr(downloads, "sha256_file", interrupted)
    with pytest.raises(Cancelled):
        manager.run("tiny.en", cancel, progress)
    assert not manager.models.installed()


def test_dangling_partial_cannot_create_external_file(manager: Downloads) -> None:
    target = manager.library / "outside-model.bin"
    partial = manager.directory("downloads") / f"tiny.en-{DIGEST}.part"
    try:
        partial.symlink_to(target)
    except OSError:
        pytest.skip("Creating a symlink requires Windows privileges")
    with pytest.raises(TranscriptionError) as error:
        manager.run("tiny.en", threading.Event(), progress)
    assert error.value.code == "models.unsafe_path"
    assert not target.exists()


# -- M34: platform compatibility ------------------------------------------------------


def other_platform() -> str:
    from openworld_moments.native import runtime_platform

    current = runtime_platform()
    return "windows-x86_64" if current != "windows-x86_64" else "macos-arm64"


def platform_manager(tmp_path: Path, platforms: list[str] | None) -> Downloads:
    library = tmp_path / "library"
    library.mkdir()
    model = read_catalog().models[0].model_dump()
    model.update(size_bytes=len(CONTENT), sha256=DIGEST, platforms=platforms)
    catalog = Catalog.model_validate({"version": 1, "models": [model]})
    calls: list[str] = []

    def opener(url: str, _offset: int) -> Response:
        calls.append(url)
        return Response(CONTENT)

    manager = Downloads(library, catalog=catalog, opener=opener)
    manager.calls = calls  # type: ignore[attr-defined]
    return manager


def test_bundled_catalog_declares_no_platform_and_stays_signed() -> None:
    """The signed catalog's bytes are unchanged, so its models install everywhere."""
    assert all(model.platforms is None for model in read_catalog().models)


def test_incompatible_artifact_is_refused_before_any_network_use(tmp_path: Path) -> None:
    from openworld_moments.native import runtime_platform

    manager = platform_manager(tmp_path, [other_platform()])
    status = manager.status()
    load("model-manager", status)
    assert status["models"][0]["compatible"] is False
    assert status["models"][0]["platforms"] == [other_platform()]
    with pytest.raises(TranscriptionError, match="Choose a model made for this computer") as err:
        manager.run("tiny.en", threading.Event(), progress)
    assert err.value.code == "models.incompatible_platform"
    assert runtime_platform() in err.value.message
    with pytest.raises(TranscriptionError, match="made for this computer"):
        manager.activate("tiny.en", DIGEST)
    assert manager.calls == []  # type: ignore[attr-defined]
    assert not manager.models.installed()
    manager.change("tiny.en", None)  # removal still works for an incompatible entry


@pytest.mark.parametrize("platforms", [None, ["any"], "current"])
def test_compatible_artifact_installs(tmp_path: Path, platforms: Any) -> None:
    from openworld_moments.native import runtime_platform

    declared = [runtime_platform(), other_platform()] if platforms == "current" else platforms
    manager = platform_manager(tmp_path, declared)
    manager.run("tiny.en", threading.Event(), progress)
    status = manager.status()
    load("model-manager", status)
    assert status["models"][0]["compatible"] is True
    assert status["models"][0]["active_sha256"] == DIGEST
    assert ("platforms" in status["models"][0]) == bool(declared)


@pytest.mark.parametrize("bad", [["macos-universal"], ["MACOS-ARM64"], [], ["any"] * 9])
def test_catalog_rejects_malformed_platforms(bad: list[str]) -> None:
    from pydantic import ValidationError

    model = read_catalog().models[0].model_dump()
    model["platforms"] = bad
    with pytest.raises(ValidationError):
        Catalog.model_validate({"version": 1, "models": [model]})


def test_api_refuses_an_incompatible_model_before_creating_a_job(tmp_path: Path) -> None:
    import secrets

    from fastapi.testclient import TestClient

    from openworld_moments.api.app import ApiSettings, create_app
    from openworld_moments.jobs.engine import JobEngine
    from openworld_moments.jobs.handlers import BUILTIN_HANDLERS
    from openworld_moments.storage import Database

    manager = platform_manager(tmp_path, [other_platform()])
    database = Database.open(manager.library / "database.sqlite3")
    token = secrets.token_hex(32)
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    app = create_app(JobEngine(database, BUILTIN_HANDLERS), settings, downloads=manager)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        response = client.post("/v1/model-manager/download", json={"name": "tiny.en"})
        assert response.status_code == 409
        assert response.json()["code"] == "models.incompatible_platform"
        assert client.get("/v1/jobs").json() == []
        status = client.get("/v1/model-manager").json()
        assert status["models"][0]["compatible"] is False
    assert manager.calls == []  # type: ignore[attr-defined]
