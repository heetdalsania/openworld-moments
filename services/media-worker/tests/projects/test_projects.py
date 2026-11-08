# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.projects.service import (
    ImportProject,
    ManualProject,
    ProjectError,
    ProjectService,
    SaveProject,
    migrate_project,
)
from openworld_moments.review.service import layout_info
from openworld_moments.sessions.fixtures import Clip, at, install
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database, StoryRepository, transaction
from openworld_moments.stories.service import StoryDecision, StoryError, StoryRequest, StoryService
from tests.stories.test_service import manual


@pytest.fixture
def library(tmp_path: Path) -> tuple[Database, str, list[str], list[Path]]:
    db = Database.open(tmp_path / "library" / "database.sqlite3")
    paths = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    for i, path in enumerate(paths):
        path.write_bytes(bytes([65 + i]) * 1001)
    with contextlib.closing(db.connect()) as conn:
        ids = install(
            conn,
            [Clip("first.mp4", at(0), duration_s=60), Clip("second.mp4", at(1), duration_s=60)],
        )
        with transaction(conn):
            for aid, path in zip(ids, paths, strict=True):
                conn.execute(
                    "UPDATE media_assets SET sha256=?,original_path=?,size_bytes=? WHERE id=?",
                    (hashlib.sha256(path.read_bytes()).hexdigest(), str(path), 1001, aid),
                )
    sessions = SessionService(db)
    sessions.recompute({})
    with contextlib.closing(db.connect()) as conn:
        sid = sessions.list_docs(conn, limit=1, offset=0)[0]["id"]
    return db, sid, ids, paths


def create(db: Database, sid: str, **changes: Any) -> dict[str, Any]:
    with contextlib.closing(db.connect()) as conn:
        key, _ = layout_info(conn, sid)
    return ProjectService(db).create(
        sid,
        ManualProject.model_validate(
            {
                "title": "Manual project",
                "layout_key": key,
                "start_ms": 50000,
                "end_ms": 70000,
                **changes,
            }
        ),
    )


def save(service: ProjectService, state: dict[str, Any], title: str) -> dict[str, Any]:
    doc = copy.deepcopy(state["document"])
    doc["project"]["title"] = title
    return service.save(
        doc["project"]["id"], SaveProject(expected_revision=state["revision"], document=doc)
    )


def test_manual_selection_uses_unique_overlap_timing_and_no_detectors(library: Any) -> None:
    db, sid, ids, paths = library
    with contextlib.closing(db.connect()) as conn, transaction(conn):
        conn.execute(
            "UPDATE session_assets SET overlap_with_previous_ms=10000 "
            "WHERE session_id=? AND order_index=1",
            (sid,),
        )
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    state = create(db, sid)
    segs = state["document"]["project"]["tracks"][0]["segments"]
    assert [
        (s["asset_id"], s["source_in_ms"], s["source_out_ms"], s["timeline_start_ms"]) for s in segs
    ] == [(ids[0], 50000, 60000, 0), (ids[1], 10000, 20000, 10000)]
    assert state["revision"] == 1
    service = ProjectService(db)
    state = save(service, state, "Renamed")
    reopened = ProjectService(Database.open(db.path)).get(state["document"]["project"]["id"])
    assert reopened["document"] == state["document"]
    assert reopened["recovery"]["project"]["title"] == "Manual project"
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before
    with contextlib.closing(db.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert (
            StoryRepository(conn).get(state["document"]["project"]["id"]).review_state == "edited"
        )


@pytest.mark.parametrize("start,end", [(-1, 1), (0, 0), (1, 0), (0, 120001)])
def test_manual_invalid_selection_leaves_no_project(library: Any, start: int, end: int) -> None:
    db, sid, _, _ = library
    with pytest.raises((ProjectError, ValueError)):
        create(db, sid, start_ms=start, end_ms=end)
    with contextlib.closing(db.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM stories").fetchone()[0] == 0


def test_stale_selection_and_revision_are_refused(library: Any) -> None:
    db, sid, _, _ = library
    with pytest.raises(ProjectError, match="Session layout changed"):
        create(db, sid, layout_key="0" * 64)
    service = ProjectService(db)
    state = create(db, sid)
    latest = save(service, state, "Newer")
    with pytest.raises(ProjectError, match="newer save"):
        save(service, state, "Stale")
    assert service.get(latest["document"]["project"]["id"])["document"] == latest["document"]
    # A lost successful reply is safe to retry without an extra revision.
    assert save(service, state, "Newer")["revision"] == latest["revision"]


def test_missing_sources_preserve_all_edits_and_recover_when_relinked(library: Any) -> None:
    db, sid, _, paths = library
    service = ProjectService(db)
    state = create(db, sid)
    pid = state["document"]["project"]["id"]
    paths[0].unlink()
    missing = service.get(pid)
    assert missing["sources"][0]["state"] == "missing"
    assert missing["document"] == state["document"]
    state = save(service, state, "Edited while offline")
    paths[0].write_bytes(b"A" * 1001)
    assert all(s["state"] == "available_unverified" for s in service.get(pid)["sources"])
    assert service.get(pid)["document"] == state["document"]


def test_portable_roundtrip_detaches_session_and_requires_explicit_hash_replacement(
    library: Any,
) -> None:
    db, sid, ids, paths = library
    service = ProjectService(db)
    state = create(db, sid, start_ms=0, end_ms=10000)
    portable = service.export(state["document"]["project"]["id"])
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    result = service.import_document(ImportProject(document=portable, bindings={ids[0]: ids[0]}))
    assert result["document"]["project"]["id"] != portable["project"]["id"]
    assert "session_id" not in result["document"]["project"]
    assert result["document"]["project"]["tracks"] == portable["project"]["tracks"]
    with pytest.raises(ProjectError, match="Confirm this source replacement"):
        service.import_document(ImportProject(document=portable, bindings={ids[0]: ids[1]}))
    replaced = service.import_document(
        ImportProject(document=portable, bindings={ids[0]: ids[1]}, confirm_replacements=[ids[0]])
    )
    assert replaced["document"]["sources"][0]["replaces_sha256"] == portable["sources"][0]["sha256"]
    assert replaced["document"]["project"]["tracks"][0]["segments"][0]["asset_id"] == ids[1]
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


def test_portable_unmapped_source_cannot_silently_use_colliding_local_identity(
    library: Any,
) -> None:
    db, sid, ids, _ = library
    service = ProjectService(db)
    state = create(db, sid, start_ms=0, end_ms=10000)
    portable = copy.deepcopy(state["document"])
    portable["sources"][0]["sha256"] = "0" * 64
    imported = service.import_document(ImportProject(document=portable))
    pid = imported["document"]["project"]["id"]
    assert service.get(pid)["sources"] == [{"asset_id": ids[0], "state": "mismatch"}]
    altered = copy.deepcopy(imported["document"])
    altered["sources"][0]["sha256"] = state["document"]["sources"][0]["sha256"]
    with pytest.raises(ProjectError, match="immutable"):
        service.save(pid, SaveProject(document=altered, expected_revision=1))


def test_portable_rejects_changed_file_short_replacement_invalid_and_cancelled(
    library: Any,
) -> None:
    db, sid, ids, paths = library
    service = ProjectService(db)
    portable = create(db, sid, start_ms=0, end_ms=10000)["document"]
    paths[1].write_bytes(b"X" * 1001)
    with pytest.raises(ProjectError, match="changed since import"):
        service.import_document(
            ImportProject(
                document=portable, bindings={ids[0]: ids[1]}, confirm_replacements=[ids[0]]
            )
        )
    paths[1].write_bytes(b"B" * 1001)
    with contextlib.closing(db.connect()) as conn:
        conn.execute("UPDATE media_assets SET duration_ms=5000 WHERE id=?", (ids[1],))
    with pytest.raises(ProjectError, match="Invalid or unsupported"):
        service.import_document(
            ImportProject(
                document=portable, bindings={ids[0]: ids[1]}, confirm_replacements=[ids[0]]
            )
        )
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ProjectError, match="cancelled"):
        service.import_document(ImportProject(document=portable, bindings={ids[0]: ids[0]}), cancel)
    invalid = copy.deepcopy(portable)
    invalid["model_version"] = 99
    with pytest.raises(ProjectError):
        service.import_document(ImportProject(document=invalid))
    with pytest.raises(ProjectError):
        service.import_document(ImportProject(document=portable, bindings={"unknown": ids[0]}))
    with contextlib.closing(db.connect()) as conn:
        assert conn.execute("SELECT count(*) FROM editor_projects").fetchone()[0] == 1


def test_legacy_migration_and_story_generation_do_not_overwrite_editor(library: Any) -> None:
    db, sid, _, _ = library
    manual(db, sid)
    stories = StoryService(db)
    stories.generate(sid, StoryRequest())
    item = stories.page(sid, StoryRequest())["items"][0]
    pid = item["candidate"]["id"]
    stories.decide(
        sid,
        pid,
        StoryDecision(
            input_key=item["candidate"]["input_key"], expected_revision=0, state="accepted"
        ),
    )
    service = ProjectService(db)
    legacy = service.get(pid)
    assert legacy["revision"] == 0 and legacy["document"]["model_version"] == 1
    saved = save(service, legacy, "Human edit")
    with pytest.raises(StoryError, match="editor changes"):
        stories.decide(
            sid,
            pid,
            StoryDecision(
                input_key=item["candidate"]["input_key"], expected_revision=1, state="rejected"
            ),
        )
    stories.generate(sid, StoryRequest(force=True))
    assert service.get(pid)["document"] == saved["document"]
    with contextlib.closing(db.connect()) as conn:
        empty = copy.deepcopy(saved["document"]["project"])
        empty.update(tracks=[], captions=[], overlays=[])
        empty["audio"] = {"gain_db": 0, "mute_ranges": []}
        assert migrate_project(conn, empty)["project"]["tracks"] == [
            {"kind": "video", "segments": []}
        ]
        unsupported = copy.deepcopy(saved["document"]["project"])
        unsupported["tracks"] *= 2
        with pytest.raises(ProjectError):
            migrate_project(conn, unsupported)


def test_process_crash_before_commit_preserves_last_committed_autosave(library: Any) -> None:
    db, sid, _, _ = library
    service = ProjectService(db)
    state = create(db, sid)
    state = save(service, state, "Last committed")
    pid = state["document"]["project"]["id"]
    child = """
import os,sys,json
from pathlib import Path
from openworld_moments.storage import Database, StoryRepository
from openworld_moments.projects.service import ProjectService,SaveProject
real=StoryRepository.save
def crash(self,story):
 real(self,story)
 os._exit(71)
StoryRepository.save=crash
state=json.loads(sys.stdin.read())
state['document']['project']['title']='Uncommitted'
ProjectService(Database.open(Path(sys.argv[1]))).save(sys.argv[2],SaveProject(document=state['document'],expected_revision=state['revision']))
"""
    result = subprocess.run(  # noqa: S603 - fixed Python program and temporary test paths
        [sys.executable, "-c", child, str(db.path), pid],
        input=json.dumps(state),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 71, result.stderr
    reopened = ProjectService(Database.open(db.path)).get(pid)
    assert reopened["document"] == state["document"] and reopened["revision"] == state["revision"]
    assert reopened["recovery"] == state["recovery"]
    with contextlib.closing(db.connect()) as conn:
        assert StoryRepository(conn).get(pid).title == "Last committed"
    restored = service.save(
        pid, SaveProject(document=reopened["recovery"], expected_revision=reopened["revision"])
    )
    assert restored["document"]["project"]["title"] == "Manual project"


def test_http_manual_save_portable_and_error_contracts(library: Any) -> None:
    db, sid, _, _ = library
    engine = JobEngine(db, {})
    settings = ApiSettings(
        token="test-token", allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    with contextlib.closing(db.connect()) as conn:
        key, _ = layout_info(conn, sid)
    with TestClient(
        create_app(engine, settings), headers={"Authorization": "Bearer test-token"}
    ) as client:
        response = client.post(
            f"/v1/sessions/{sid}/projects",
            json={"title": "HTTP", "layout_key": key, "start_ms": 0, "end_ms": 1000},
        )
        assert response.status_code == 201, response.text
        state = response.json()
        pid = state["document"]["project"]["id"]
        assert client.get(f"/v1/projects/{pid}").status_code == 200
        portable = client.get(f"/v1/projects/{pid}/portable").json()
        assert client.post("/v1/projects/import", json={"document": portable}).status_code == 201
        state["document"]["project"]["title"] = "Saved"
        assert (
            client.put(
                f"/v1/projects/{pid}", json={"document": state["document"], "expected_revision": 1}
            ).status_code
            == 200
        )
        state["document"]["project"]["title"] = "Stale"
        bad = client.put(
            f"/v1/projects/{pid}", json={"document": state["document"], "expected_revision": 1}
        )
        assert bad.status_code == 409 and bad.json()["code"] == "project.revision_conflict"
        assert client.get("/v1/projects/prj_00000000000000000000000000").status_code == 404


def test_relink_keeps_project_identity_and_revision_history(library: Any) -> None:
    from openworld_moments.projects.service import RelinkProject

    db, sid, ids, _ = library
    service = ProjectService(db)
    state = create(db, sid, start_ms=0, end_ms=10000)
    pid = state["document"]["project"]["id"]
    with pytest.raises(ProjectError, match="Confirm this source replacement"):
        service.relink(pid, RelinkProject(expected_revision=1, bindings={ids[0]: ids[1]}))
    relinked = service.relink(
        pid,
        RelinkProject(
            expected_revision=1, bindings={ids[0]: ids[1]}, confirm_replacements=[ids[0]]
        ),
    )
    assert relinked["revision"] == 2
    assert relinked["document"]["project"]["id"] == pid
    assert relinked["document"]["project"]["session_id"] == sid
    assert relinked["recovery"] == state["document"]
    with pytest.raises(ProjectError, match="newer save"):
        service.relink(
            pid,
            RelinkProject(
                expected_revision=1, bindings={ids[0]: ids[1]}, confirm_replacements=[ids[0]]
            ),
        )


def test_concurrent_writers_cannot_overwrite_each_other(library: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor

    db, sid, _, _ = library
    service = ProjectService(db)
    state = create(db, sid)

    def attempt(title: str) -> str:
        try:
            save(service, state, title)
            return title
        except ProjectError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["Writer A", "Writer B"]))
    assert results.count("project.revision_conflict") == 1
    winner = next(r for r in results if r != "project.revision_conflict")
    current = service.get(state["document"]["project"]["id"])
    assert current["revision"] == 2 and current["document"]["project"]["title"] == winner


def test_unmapped_portable_sources_require_explicit_binding_even_with_matching_local_id(
    library: Any,
) -> None:
    from openworld_moments.projects.service import RelinkProject

    db, sid, ids, _ = library
    service = ProjectService(db)
    portable = create(db, sid, start_ms=0, end_ms=10000)["document"]
    imported = service.import_document(ImportProject(document=portable))
    pid = imported["document"]["project"]["id"]
    assert imported["document"]["sources"][0]["requires_relink"] is True
    assert service.get(pid)["sources"] == [{"asset_id": ids[0], "state": "missing"}]
    linked = service.relink(pid, RelinkProject(expected_revision=1, bindings={ids[0]: ids[0]}))
    assert "requires_relink" not in linked["document"]["sources"][0]
    assert service.get(pid)["sources"][0]["state"] == "available_unverified"
