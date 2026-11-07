# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session transcription through the real path (M18): generated clips → import →
proxy → FFmpeg 16 kHz WAV → a whisper.cpp test double → persisted, session-timed
segments. Covers caching, resume after cancellation (engine process killed, scratch
removed), missing model/engine, failures that never leak text, deletion that keeps
media, the job/API surface and the CLI. All media is generated."""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers, transcribe_handler
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database, DerivedArtifactRepository
from openworld_moments.transcripts.service import STAGING, Transcriber
from openworld_moments.transcripts.whisper import (
    Engine,
    TranscriptionCancelled,
    TranscriptionError,
    sha256_file,
)
from tests.media.test_audio import FLOOR, SPEECH, make_clip
from tests.worker.conftest import wait_for

HERE = Path(__file__).parents[1] / "transcripts"
FAKE = HERE / "fake_whisper.py"
OUTPUT = HERE / "whisper-full.json"


def fake_engine(cancel: threading.Event | None = None) -> Engine:
    return Engine((sys.executable, str(FAKE)), FAKE, "1.7.6", sha256_file(FAKE))


def no_engine(cancel: threading.Event | None = None) -> Engine:
    raise TranscriptionError("transcription.engine_missing", "Install whisper.cpp to transcribe.")


class Setup:
    def __init__(self, root: Path, tools: MediaTools, ffmpeg: ToolInfo, monkeypatch: Any) -> None:
        self.root = root
        self.database = Database.open(root / "library" / "database.sqlite3")
        self.tools = tools
        self.derived = DerivedMedia(self.database, tools)
        self.transcriber = Transcriber(self.database, tools, self.derived, engine=fake_engine)
        self.control = root / "control.json"
        self.calls = root / "calls.log"
        self.heartbeat = root / "heartbeat"
        self.configure()
        monkeypatch.setenv("OWM_FAKE_WHISPER", str(self.control))
        model = root / "ggml-base.en.bin"
        model.write_bytes(b"lmgg" + b"\0" * 8192)
        self.transcriber.models.install(model, "base.en", "MIT")
        self.clips = [
            make_clip(ffmpeg, root / "a.mp4", [f"{FLOOR}+{SPEECH}"], seconds=6),
            # Different bytes, or the import would recognise the same file twice.
            make_clip(ffmpeg, root / "b.mp4", [f"0.003*sin(2*PI*613*t)+{SPEECH}"], seconds=6),
        ]

    def configure(self, **control: Any) -> None:
        self.control.write_text(
            json.dumps(
                {
                    "calls": str(self.calls),
                    "heartbeat": str(self.heartbeat),
                    "output": str(OUTPUT),
                    **control,
                }
            ),
            "utf-8",
        )

    def call_count(self) -> int:
        return len(self.calls.read_text("utf-8").splitlines()) if self.calls.exists() else 0

    def session(self, clips: list[Path] | None = None) -> str:
        Importer(self.database, self.tools).run_import(
            {"paths": [str(c) for c in clips or self.clips], "mode": "reference"},
            job_id=new_id("job"),
            cancel=threading.Event(),
            progress=lambda *_: None,
        )
        SessionService(self.database).recompute({})
        with contextlib.closing(self.database.connect()) as conn:
            docs = SessionService(self.database).list_docs(conn, limit=10, offset=0)
        assert len(docs) == 1
        return str(docs[0]["id"])

    def run(self, sid: str, **extra: Any) -> dict[str, Any]:
        return self.transcriber.run(
            {"session_id": sid, "model": "base.en", **extra}, job_id=new_id("job")
        )


@pytest.fixture
def setup(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo, monkeypatch: pytest.MonkeyPatch
) -> Setup:
    return Setup(tmp_path, tools, ffmpeg, monkeypatch)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_transcribes_every_clip_into_session_time_and_caches(setup: Setup) -> None:
    sid = setup.session()
    result = setup.run(sid)
    assert [(o["status"], o["segment_count"], o.get("language")) for o in result["outcomes"]] == [
        ("computed", 2, "en"),
        ("computed", 2, "en"),
    ]
    calls = [json.loads(line) for line in setup.calls.read_text("utf-8").splitlines()]
    assert [c["language"] for c in calls] == ["auto", "auto"]
    transcript = setup.transcriber.transcript(sid)
    segments = transcript["segments"]
    assert [s["text"] for s in segments] == ["Meet me at the bridge.", "Go, go!"] * 2
    # The second clip follows the first in unique session time (6 s clips, no overlap).
    assert [s["start_ms"] for s in segments] == [0, 2500, 6000, 8500]
    assert [s["source_start_ms"] for s in segments] == [0, 2500, 0, 2500]
    bridge = segments[2]["words"][4]
    assert (bridge["text"], bridge["start_ms"], bridge["source_start_ms"]) == (
        "bridge.",
        6750,
        750,
    )
    provenance = segments[0]["transcriber"]
    assert provenance["engine"] == "whisper.cpp" and provenance["model"] == "base.en"
    assert provenance["model_sha256"] == setup.transcriber.models.get("base.en").sha256
    # Cached: no engine call; force recomputes; a language choice is a new key.
    assert [o["status"] for o in setup.run(sid)["outcomes"]] == ["cached", "cached"]
    assert setup.call_count() == 2
    assert [o["status"] for o in setup.run(sid, force=True)["outcomes"]] == ["computed"] * 2
    assert [o["status"] for o in setup.run(sid, language="en")["outcomes"]] == ["computed"] * 2
    assert setup.call_count() == 6
    assert len(setup.transcriber.transcript(sid)["segments"]) == 4  # replaced, not appended


def test_cancel_kills_the_engine_removes_scratch_and_resumes(setup: Setup) -> None:
    sid = setup.session()
    setup.configure(modes={"2": "hang"})
    cancel = threading.Event()
    failure: list[BaseException] = []

    def work() -> None:
        try:
            setup.transcriber.run(
                {"session_id": sid, "model": "base.en"}, job_id=new_id("job"), cancel=cancel
            )
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    wait_for(setup.heartbeat.exists, timeout=60)
    cancel.set()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert failure and isinstance(failure[0], TranscriptionCancelled)
    beat = setup.heartbeat.read_text("utf-8")
    time.sleep(0.4)
    assert setup.heartbeat.read_text("utf-8") == beat, "the engine process was not stopped"
    staging = setup.derived.paths.root / STAGING
    assert not staging.exists() or not any(staging.iterdir())
    # The first clip committed before the cancel; resuming only redoes the second.
    setup.configure()
    result = setup.run(sid)
    assert [o["status"] for o in result["outcomes"]] == ["cached", "computed"]


def test_engine_failure_is_explained_without_transcript_text(setup: Setup) -> None:
    sid = setup.session()
    setup.configure(modes={"1": "fail", "2": "garbage"})
    result = setup.run(sid)
    codes = [o["error"]["code"] for o in result["outcomes"]]
    assert codes == ["transcription.engine_failed", "transcription.invalid_output"]
    assert "BRIDGE" not in json.dumps(result).upper()
    assert setup.transcriber.transcript(sid)["segments"] == []
    # Through the job handler this is a partial failure that keeps the detailed result.
    from types import SimpleNamespace

    from openworld_moments.jobs.engine import JobFailure

    setup.configure(mode="fail")
    context = SimpleNamespace(
        params={"session_id": sid, "model": "base.en", "force": True},
        job_id=new_id("job"),
        cancel_event=threading.Event(),
        progress=lambda *_: None,
    )
    with pytest.raises(JobFailure) as caught:
        transcribe_handler(setup.transcriber).run(context)  # type: ignore[arg-type]
    assert caught.value.code == "transcription.partial_failure"


def test_clip_without_audio_is_skipped_others_complete(setup: Setup, ffmpeg: ToolInfo) -> None:
    silent_video = make_clip(ffmpeg, setup.root / "c.mp4", None, seconds=3)
    sid = setup.session([*setup.clips, silent_video])
    outcomes = setup.run(sid)["outcomes"]
    assert [o["status"] for o in outcomes] == ["computed", "computed", "skipped"]
    assert outcomes[2]["error"]["code"] == "transcription.no_audio"


def test_missing_model_or_engine_is_refused_and_nothing_downloads(setup: Setup) -> None:
    sid = setup.session()
    with pytest.raises(TranscriptionError) as caught:
        setup.transcriber.run({"session_id": sid, "model": "small.en"}, job_id=new_id("job"))
    assert caught.value.code == "transcription.model_missing"
    handler = transcribe_handler(setup.transcriber)
    with pytest.raises(ValueError, match="not installed"):
        handler.validate({"session_id": sid, "model": "small.en"})
    with pytest.raises(ValueError, match="language"):
        handler.validate({"session_id": sid, "model": "base.en", "language": "english"})
    offline = Transcriber(setup.database, setup.tools, setup.derived, engine=no_engine)
    status = offline.status()
    assert status["engine"] == {
        "available": False,
        "reason": "Install whisper.cpp to transcribe.",
    }
    assert [m["name"] for m in status["installed"]] == ["base.en"]
    assert status["catalog"] and setup.call_count() == 0
    with pytest.raises(TranscriptionError, match=r"whisper\.cpp"):
        offline.check_request("base.en")


def test_a_changed_model_file_is_not_used(setup: Setup) -> None:
    sid = setup.session()
    model = setup.transcriber.models.get("base.en").path
    data = bytearray(model.read_bytes())
    data[100] = 1  # same size, different bytes
    model.write_bytes(bytes(data))
    with pytest.raises(TranscriptionError) as caught:
        setup.run(sid)
    assert caught.value.code == "transcription.model_changed"
    assert setup.call_count() == 0


def test_deleting_the_transcript_keeps_media_and_events(setup: Setup) -> None:
    sid = setup.session()
    setup.run(sid)
    with contextlib.closing(setup.database.connect()) as conn:
        aid = conn.execute("SELECT asset_id FROM session_assets LIMIT 1").fetchone()[0]
        row = DerivedArtifactRepository(conn).get(aid, "proxy")
        events_before = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert row is not None and row.relpath is not None
    proxy = setup.derived.paths.resolve(row.relpath)
    assert proxy is not None
    before = [digest(c) for c in setup.clips], digest(proxy)
    assert setup.transcriber.delete(sid) == {"deleted_segments": 4}
    assert setup.transcriber.transcript(sid)["segments"] == []
    assert ([digest(c) for c in setup.clips], digest(proxy)) == before
    with contextlib.closing(setup.database.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM transcript_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == events_before
        assert DerivedArtifactRepository(conn).get(aid, "proxy") is not None
    # Rebuild recomputes rather than reusing deleted results.
    assert [o["status"] for o in setup.run(sid)["outcomes"]] == ["computed", "computed"]


def test_job_and_api_surface(setup: Setup) -> None:
    sid = setup.session()
    settings = ApiSettings(
        secrets.token_hex(32), frozenset({"testserver"}), require_loopback_peer=False
    )
    engine = JobEngine(
        setup.database,
        build_handlers(
            setup.tools,
            database=setup.database,
            derived=setup.derived,
            transcriber=setup.transcriber,
        ),
    )
    app = create_app(engine, settings, derived=setup.derived, transcriber=setup.transcriber)
    with TestClient(app) as client:
        assert client.get("/v1/transcription/models").status_code == 401
        client.headers["Authorization"] = f"Bearer {settings.token}"
        status = client.get("/v1/transcription/models").json()
        assert status["engine"]["available"] is True
        assert [m["name"] for m in status["installed"]] == ["base.en"]
        refused = client.post(f"/v1/sessions/{sid}/transcribe", json={"model": "small.en"})
        assert refused.status_code == 422
        assert "not installed" in json.dumps(refused.json())
        response = client.post(
            f"/v1/sessions/{sid}/transcribe",
            json={"model": "base.en", "idempotency_key": "transcribe-once"},
        )
        assert response.status_code == 201
        job_id = response.json()["id"]
        assert response.json()["kind"] == "transcribe"
        wait_for(
            lambda: client.get(f"/v1/jobs/{job_id}").json()["state"] in ("ready", "failed"),
            timeout=60,
        )
        job = client.get(f"/v1/jobs/{job_id}").json()
        assert job["state"] == "ready", job
        transcript = client.get(f"/v1/sessions/{sid}/transcript").json()
        assert len(transcript["segments"]) == 4
        assert client.delete(f"/v1/sessions/{sid}/transcript").json() == {"deleted_segments": 4}
        assert client.get(f"/v1/sessions/{sid}/transcript").json()["segments"] == []
        missing = "ses_01JCBQ00000000000000000099"
        assert client.get(f"/v1/sessions/{missing}/transcript").status_code == 404
        assert client.delete(f"/v1/sessions/{missing}/transcript").status_code == 404


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed test argv
        [sys.executable, "-m", "openworld_moments.detectors", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


def test_cli_installs_lists_and_removes_models(tmp_path: Path) -> None:
    import os

    model = tmp_path / "ggml-tiny.en.bin"
    model.write_bytes(b"lmgg" + b"\0" * 4096)
    library = tmp_path / "library"
    installed = run_cli(
        "models", "install", "--library", str(library), "tiny.en", str(model), "--license", "MIT"
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert json.loads(installed.stdout)["name"] == "tiny.en"
    listed = run_cli("models", "list", "--library", str(library))
    assert [m["name"] for m in json.loads(listed.stdout)] == ["tiny.en"]
    bad = run_cli(
        "models", "install", "--library", str(library), "x", str(tmp_path), "--license", "MIT"
    )
    assert bad.returncode == 1 and json.loads(bad.stdout)["error"]["code"]
    assert run_cli("models", "remove", "--library", str(library), "tiny.en").returncode == 0
    assert json.loads(run_cli("models", "list", "--library", str(library)).stdout) == []
    env = {**os.environ, "OWM_WHISPER": str(tmp_path / "no-such-engine")}
    doctor = run_cli("speech", "doctor", env=env)
    assert doctor.returncode == 1
    assert json.loads(doctor.stdout)["error"]["code"] == "transcription.engine_missing"
