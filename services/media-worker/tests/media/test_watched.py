# SPDX-License-Identifier: AGPL-3.0-or-later
"""Watched folders on the worker side (M07): patterns, decisions, and endpoints."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load

from openworld_moments.media.tools import ToolInfo
from openworld_moments.storage import (
    Database,
    JobRepository,
    WatchedFileRow,
    WatchedFolderRepository,
    transaction,
)
from openworld_moments.watched import service
from openworld_moments.watched.patterns import is_candidate
from tests.media.test_import_api import _finished, _make_client

CASES = (
    Path(__file__).resolve().parents[4] / "packages/contracts/fixtures/watched-folder/patterns.json"
)


@pytest.mark.parametrize(
    "case", json.loads(CASES.read_text("utf-8"))["cases"], ids=lambda c: f"{c['path']}"
)
def test_shared_pattern_cases(case: dict[str, Any]) -> None:
    assert is_candidate(case["path"], case["include"], case["exclude"]) is case["candidate"]


# -- decisions, unit level ------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Any]:
    database = Database.open(tmp_path / "library" / "database.sqlite3")
    folder = tmp_path / "captures"
    folder.mkdir()
    with closing(database.connect()) as conn:
        with transaction(conn):
            WatchedFolderRepository(conn).create(path=str(folder), source_kind="xbox")
        yield conn


def _folder(conn: Any) -> Any:
    return WatchedFolderRepository(conn).all()[0]


def _job(conn: Any, job_id: str, state: str, **extra: Any) -> None:
    doc: dict[str, Any] = {
        "schema_version": "1.5",
        "id": job_id,
        "kind": "import",
        "state": state,
        "attempt": 1,
        "created_at": "2026-11-20T05:40:10Z",
        **extra,
    }
    if state in ("ready", "failed", "cancelled"):
        doc.setdefault("started_at", "2026-11-20T05:40:11Z")
        doc.setdefault("finished_at", "2026-11-20T05:40:12Z")
    with transaction(conn):
        JobRepository(conn).save(load("job", doc))  # type: ignore[arg-type]


def _track(conn: Any, job_id: str | None, attempts: int = 1) -> None:
    with transaction(conn):
        WatchedFolderRepository(conn).save_file(
            WatchedFileRow(
                folder_id=_folder(conn).id,
                relative_path="clip.mp4",
                size_bytes=100,
                mtime_ns=5,
                attempts=attempts,
                job_id=job_id,
                updated_at="2026-11-20T05:40:12Z",
            )
        )


JOB = "job_01JCBQ00000000000000000040"


def test_new_and_changed_versions_are_imported(db: Any) -> None:
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5) == (1, {})
    _job(db, JOB, "ready")
    _track(db, JOB)
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5)[1]["action"] == "known"
    assert service.decide(db, _folder(db), "clip.mp4", 200, 5) == (1, {})  # grew
    assert service.decide(db, _folder(db), "clip.mp4", 100, 6) == (1, {})  # rewritten


@pytest.mark.parametrize(
    ("state", "action"), [("queued", "in_progress"), ("probing", "in_progress")]
)
def test_running_import_is_not_repeated(db: Any, state: str, action: str) -> None:
    _job(db, JOB, state, started_at="2026-11-20T05:40:11Z") if state != "queued" else _job(
        db, JOB, state
    )
    _track(db, JOB)
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5) == (
        None,
        {"action": action, "job_id": JOB},
    )


def test_unimportable_version_is_not_retried(db: Any) -> None:
    error = {"code": "media.damaged", "message": "Damaged.", "retryable": False}
    _job(db, JOB, "failed", error=error)
    _track(db, JOB)
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5)[1]["action"] == "known"


def test_retryable_failure_backs_off_then_retries(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    error = {"code": "import.source_changed", "message": "Changed.", "retryable": True}
    _job(db, JOB, "failed", error=error)
    _track(db, JOB, attempts=2)
    retry = service.retry_at(2, "2026-11-20T05:40:12Z")
    assert retry == "2026-11-20T05:42:12.000Z"  # 60 s x 2^(2-1)
    monkeypatch.setattr(service, "utc_now", lambda: "2026-11-20T05:41:00.000Z")
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5) == (
        None,
        {"action": "backoff", "job_id": JOB, "retry_at": retry},
    )
    monkeypatch.setattr(service, "utc_now", lambda: "2026-11-20T05:43:00.000Z")
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5) == (3, {})


def test_retries_stop_after_max_attempts(db: Any) -> None:
    error = {"code": "import.disk_full", "message": "Full.", "retryable": True}
    _job(db, JOB, "failed", error=error)
    _track(db, JOB, attempts=service.MAX_ATTEMPTS)
    assert service.decide(db, _folder(db), "clip.mp4", 100, 5)[1]["action"] == "known"


def test_cancelled_import_is_retried_with_backoff(db: Any) -> None:
    _job(db, JOB, "cancelled")
    _track(db, JOB)
    state = service.file_state(db, WatchedFolderRepository(db).file(_folder(db).id, "clip.mp4"))  # type: ignore[arg-type]
    assert state["state"] == "failed" and state["retryable"] is True


@pytest.mark.parametrize(
    "rel",
    [
        "../escape.mp4",
        "a/../../escape.mp4",
        "/abs/clip.mp4",
        "C:/clip.mp4",
        "a\\b.mp4",
        "./clip.mp4",
        "a//b.mp4",
        "",
    ],
)
def test_paths_cannot_leave_the_folder(db: Any, rel: str) -> None:
    with pytest.raises(service.WatchError) as caught:
        service.decide(db, _folder(db), rel, 100, 5)
    assert caught.value.code in ("watch.invalid_path", "watch.invalid_request")


def test_patterns_and_recursion_are_enforced(db: Any) -> None:
    folder = _folder(db)
    assert service.decide(db, folder, "notes.txt", 100, 5)[1] == {"action": "ignored"}
    assert service.decide(db, folder, ".hidden.mp4", 100, 5)[1] == {"action": "ignored"}
    with transaction(db):
        flat = WatchedFolderRepository(db).update(folder.id, {"recursive": False})
    with pytest.raises(service.WatchError, match="subfolders"):
        service.decide(db, flat, "sub/clip.mp4", 100, 5)


def test_disabled_folder_does_no_work(db: Any) -> None:
    with transaction(db):
        off = WatchedFolderRepository(db).update(_folder(db).id, {"enabled": False})
    with pytest.raises(service.WatchError) as caught:
        service.decide(db, off, "clip.mp4", 100, 5)
    assert caught.value.status == 409


# -- endpoints ------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path: Path, ffprobe: ToolInfo) -> Iterator[TestClient]:
    with _make_client(tmp_path / "library", ffprobe) as client:
        yield client


def test_folder_lifecycle(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "Xbox Game DVR"
    folder.mkdir()
    (folder / "keep.txt").write_text("never touched", "utf-8")
    created = api.post("/v1/watched-folders", json={"path": str(folder), "source_kind": "xbox"})
    assert created.status_code == 201, created.text
    doc = created.json()
    load("watched-folder", doc)
    assert doc["mode"] == "reference" and doc["recursive"] is True and doc["enabled"] is True
    assert doc["exclude"] == [".*", "**/.*/**"] and doc["availability"] == "unknown"

    again = api.post("/v1/watched-folders", json={"path": str(folder)})
    assert again.status_code == 409 and again.json()["code"] == "watch.already_watched"
    missing = api.post("/v1/watched-folders", json={"path": str(tmp_path / "nope")})
    assert missing.status_code == 422 and missing.json()["code"] == "watch.not_a_folder"
    bad = api.post("/v1/watched-folders", json={"path": str(folder), "include": ["a\\b"]})
    assert bad.status_code == 422

    changed = api.patch(
        f"/v1/watched-folders/{doc['id']}", json={"enabled": False, "include": ["Halo/**"]}
    )
    assert changed.json()["enabled"] is False and changed.json()["include"] == ["Halo/**"]
    assert api.patch(f"/v1/watched-folders/{doc['id']}", json={"path": "/x"}).status_code == 422
    assert [f["id"] for f in api.get("/v1/watched-folders").json()] == [doc["id"]]

    assert api.delete(f"/v1/watched-folders/{doc['id']}").status_code == 204
    assert api.get(f"/v1/watched-folders/{doc['id']}").status_code == 404
    assert (folder / "keep.txt").read_text("utf-8") == "never touched"


def test_report_imports_once_per_version(api: TestClient, media_dir: Path, tmp_path: Path) -> None:
    folder = tmp_path / "captures"
    (folder / "Halo").mkdir(parents=True)
    clip = folder / "Halo" / "Capture 01.mp4"
    shutil.copyfile(media_dir / "h264_aac.mp4", clip)
    fid = api.post("/v1/watched-folders", json={"path": str(folder), "source_kind": "xbox"}).json()[
        "id"
    ]
    report = {
        "relative_path": "Halo/Capture 01.mp4",
        "size_bytes": clip.stat().st_size,
        "mtime_ns": clip.stat().st_mtime_ns,
    }

    # An event storm: many reports of the same version, one import.
    decisions = [
        api.post(f"/v1/watched-folders/{fid}/files", json=report).json() for _ in range(20)
    ]
    assert decisions[0]["action"] == "queued"
    assert {d["action"] for d in decisions[1:]} <= {"in_progress", "known"}
    job = _finished(api, decisions[0]["job_id"])
    assert job["state"] == "ready" and job["params"]["source_kind"] == "xbox"
    assert job["idempotency_key"].startswith(f"watch:{fid}:")
    assert api.post(f"/v1/watched-folders/{fid}/files", json=report).json()["action"] == "known"
    imports = [j for j in api.get("/v1/jobs").json() if j["kind"] == "import"]
    assert len(imports) == 1

    (file_doc,) = api.get(f"/v1/watched-folders/{fid}/files").json()
    assert file_doc["state"] == "imported" and file_doc["asset_id"].startswith("ast_")
    stats = api.get(f"/v1/watched-folders/{fid}").json()["stats"]
    assert stats == {"tracked": 1, "imported": 1, "in_progress": 0, "failed": 0}
    assert sorted(p.name for p in folder.rglob("*")) == ["Capture 01.mp4", "Halo"]

    ignored = api.post(
        f"/v1/watched-folders/{fid}/files", json={**report, "relative_path": "notes.txt"}
    )
    assert ignored.json() == {"action": "ignored"}
    escape = api.post(
        f"/v1/watched-folders/{fid}/files", json={**report, "relative_path": "../outside.mp4"}
    )
    assert escape.status_code == 422 and escape.json()["code"] == "watch.invalid_path"


def test_scan_reports_set_availability(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "drive"
    folder.mkdir()
    fid = api.post("/v1/watched-folders", json={"path": str(folder)}).json()["id"]
    error = {"code": "watch.folder_unavailable", "message": "Cannot be read.", "retryable": True}
    down = api.post(f"/v1/watched-folders/{fid}/scans", json={"available": False, "error": error})
    assert down.json()["availability"] == "unavailable"
    assert down.json()["last_error"]["code"] == "watch.folder_unavailable"
    assert "last_scan_at" not in down.json()
    up = api.post(f"/v1/watched-folders/{fid}/scans", json={"available": True, "scanned": True})
    assert up.json()["availability"] == "available" and "last_error" not in up.json()
    assert "last_scan_at" in up.json()
    assert (
        api.post(f"/v1/watched-folders/{fid}/scans", json={"available": "yes"}).status_code == 422
    )
    assert api.post("/v1/watched-folders/999/scans", json={"available": True}).status_code == 404
