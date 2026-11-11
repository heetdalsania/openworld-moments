# SPDX-License-Identifier: AGPL-3.0-or-later
"""M31 diagnostics: the report helps support without carrying anything personal."""

from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import ContractError, load

from openworld_moments import diagnostics
from openworld_moments.redaction import Redactor
from openworld_moments.storage import Database
from tests.worker.conftest import wait_for

TOKEN = "f" * 64
PERSONAL = (
    "/Users/alex/Videos/Heist night.mp4",
    r"C:\Users\Alex\Videos\Heist night.mp4",
    r"\\nas\share\captures\clip.mkv",
    "Heist night.mp4",
    "beach_chase-02.MOV",
    TOKEN,
    "alex",
    "Alex",
)


def failure(message: str, code: str = "import.unreadable", kind: str = "import") -> dict[str, Any]:
    return {
        "kind": kind,
        "state": "failed",
        "created_at": "2026-11-10T08:00:00Z",
        "error": {"code": code, "message": message, "retryable": False},
    }


JOBS = [
    failure("Could not read /Users/alex/Videos/Heist night.mp4: moov atom missing"),
    failure(r"C:\Users\Alex\Videos\Heist night.mp4 is locked by another program"),
    failure(r"Share \\nas\share\captures\clip.mkv went away"),
    failure('The file "Heist night.mp4" is not a video'),
    failure("beach_chase-02.MOV has no audio stream", code="probe.no_audio", kind="probe"),
    failure(f"Rejected Authorization: Bearer {TOKEN}", code="auth.invalid_token", kind="render"),
    {"kind": "import", "state": "ready", "created_at": "2026-11-10T09:00:00Z", "error": None},
    {"kind": "import", "state": "ready", "created_at": "2026-11-10T09:01:00Z", "error": None},
]

DOCTOR = {
    "ready": True,
    "packaged": True,
    "platform": "Windows",
    "architecture": "AMD64",
    "free_bytes": 5 * 1024**3,
    "checks": [
        {
            "id": "permissions",
            "status": "pass",
            "message": r"Library C:\Users\Alex\AppData\Roaming\owm\library is writable.",
        }
    ],
    "tools": [{"name": "ffmpeg", "version": "9.0.2", "origin": "bundle", "license": "GPL"}],
}


def report(tmp_path: Path, *, include_messages: bool) -> dict[str, Any]:
    database = Database.open(tmp_path / "database.sqlite3")
    return diagnostics.build_report(
        worker={"worker_version": "0.1.0", "api_version": "1", "schema_version": "1.24"},
        doctor_report=DOCTOR,
        database_path=database.path,
        jobs=JOBS,
        models={"models": [{"name": "tiny.en", "revision": "abc", "active_sha256": None}]},
        include_messages=include_messages,
        secrets=[TOKEN],
        now=datetime(2026, 11, 11, 12, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize("include_messages", [False, True])
def test_report_never_carries_paths_names_or_tokens(tmp_path: Path, include_messages: bool) -> None:
    doc = report(tmp_path, include_messages=include_messages)
    load("diagnostics-report", doc)
    text = diagnostics.render(doc, [TOKEN])
    for value in PERSONAL:
        assert value not in text, value
    assert "Heist" not in text and "beach_chase" not in text
    # Facts that help support are kept.
    assert doc["library"]["clips"] == 0 and doc["library"]["database_schema"] > 0
    codes = [f["code"] for f in doc["jobs"]["recent_failures"]]
    assert codes.count("import.unreadable") == 4 and "probe.no_audio" in codes
    assert {"kind": "import", "state": "ready", "count": 2} in doc["jobs"]["totals"]
    assert doc["system"]["free_mib"] == 5 * 1024
    assert doc["models"] == [{"name": "tiny.en", "revision": "abc", "installed": False}]


def test_failure_messages_are_omitted_unless_the_user_opts_in(tmp_path: Path) -> None:
    default = report(tmp_path, include_messages=False)
    assert all("message" not in f for f in default["jobs"]["recent_failures"])
    assert default["privacy"]["failure_messages"] == "omitted"

    opted = report(tmp_path, include_messages=True)
    assert opted["privacy"]["failure_messages"] == "included, redacted"
    messages = [f["message"] for f in opted["jobs"]["recent_failures"]]
    assert messages[0] == "Could not read [path] [file]: moov atom missing"
    assert messages[1] == "[path] [file] is locked by another program"
    assert messages[3] == 'The file "[file]" is not a video'
    assert messages[4] == "[file] has no audio stream"
    assert "[redacted]" in messages[5]


def test_contract_rejects_messages_without_opt_in(tmp_path: Path) -> None:
    doc = report(tmp_path, include_messages=True)
    doc["privacy"]["failure_messages"] = "omitted"
    with pytest.raises(ContractError, match="messages present although omitted"):
        load("diagnostics-report", doc)


def test_missing_database_and_doctor_still_produce_a_report(tmp_path: Path) -> None:
    doc = diagnostics.build_report(
        worker={"worker_version": "0.1.0", "api_version": "1", "schema_version": "1.24"},
        doctor_report=None,
        database_path=tmp_path / "absent.sqlite3",
        jobs=[],
        models=None,
        include_messages=False,
    )
    load("diagnostics-report", doc)
    assert doc["system"] == {"available": False}
    assert set(doc["library"].values()) == {None}
    assert not (tmp_path / "absent.sqlite3").exists()  # opened read-only, never created


def test_messages_are_bounded_and_single_line() -> None:
    redactor = Redactor()
    text = diagnostics.scrub_message("line one\nline two " + "x" * 1000, redactor)
    assert "\n" not in text and len(text) == diagnostics.MAX_MESSAGE
    assert diagnostics.scrub_message("   ", redactor) == "[empty]"


def test_filename_is_plain() -> None:
    assert diagnostics.filename({"generated_at": "2026-11-11T12:30:00Z"}) == (
        "openworld-moments-diagnostics-20261111.json"
    )
    assert diagnostics.filename({}) == "openworld-moments-diagnostics-report.json"


def test_api_previews_exactly_what_is_saved(tmp_path: Path) -> None:
    from openworld_moments.api.app import ApiSettings, create_app
    from openworld_moments.jobs.engine import JobEngine
    from openworld_moments.jobs.handlers import BUILTIN_HANDLERS

    token = secrets.token_hex(32)
    database = Database.open(tmp_path / "database.sqlite3")
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    with TestClient(create_app(JobEngine(database, BUILTIN_HANDLERS), settings)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        job = client.post(
            "/v1/jobs",
            json={"kind": "diagnostic", "params": {"steps": 1, "step_ms": 0, "fail_at": 1}},
        ).json()
        wait_for(lambda: client.get(f"/v1/jobs/{job['id']}").json()["state"] == "failed")

        response = client.post("/v1/diagnostics", json={})
        assert response.status_code == 200
        body = response.json()
        load("diagnostics-report", body["report"])
        doc = body["report"]
        assert body["content"] == diagnostics.render(body["report"], [token])
        assert json.loads(body["content"]) == body["report"]
        assert re.fullmatch(r"openworld-moments-diagnostics-\d{8}\.json", body["filename"])
        assert token not in body["content"]
        failures = doc["jobs"]["recent_failures"]
        assert failures[0]["code"] == "diagnostic.requested_failure"
        assert "message" not in failures[0]

        opted = client.post("/v1/diagnostics", json={"include_messages": True}).json()
        assert opted["report"]["jobs"]["recent_failures"][0]["message"] == (
            "Failed at step 1 as requested."
        )

        refused = client.post("/v1/diagnostics", json={"include_paths": True})
        assert refused.status_code == 422
