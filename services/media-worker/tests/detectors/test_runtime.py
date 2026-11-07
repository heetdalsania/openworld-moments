# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterable
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load, normalize

from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors import service as module
from openworld_moments.detectors.example import BrightRegion
from openworld_moments.detectors.profiles import (
    DEFAULT_CATALOG,
    ProfileCatalog,
    ProfileError,
    compatibility,
    read_manifest,
)
from openworld_moments.detectors.sdk import (
    AnalysisCancelled,
    AnalysisContext,
    AnalysisError,
    Detection,
    Frame,
)
from openworld_moments.detectors.service import Analyzer
from openworld_moments.ids import new_id
from openworld_moments.media.tools import MediaTools
from openworld_moments.sessions.fixtures import Clip, at, install
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database, EventRepository


def manifest() -> dict[str, Any]:
    return read_manifest(DEFAULT_CATALOG / "generic-open-world" / "profile.json")


def write_profile(root: Path, doc: dict[str, Any]) -> None:
    path = root / doc["id"] / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), "utf-8")


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Analyzer, str, dict[str, Any]]:
    database = Database.open(tmp_path / "library" / "database.sqlite3")
    with contextlib.closing(database.connect()) as conn:
        install(conn, [Clip("one.mp4", at(0))])
    sessions = SessionService(database)
    sessions.recompute({})
    with contextlib.closing(database.connect()) as conn:
        sid = sessions.list_docs(conn, limit=1, offset=0)[0]["id"]
    root = tmp_path / "profiles"
    write_profile(root, manifest())
    tools = MediaTools()
    analyzer = Analyzer(
        database, tools, DerivedMedia(database, tools), catalog=ProfileCatalog(root)
    )
    inputs: dict[str, Any] = {"key": "a" * 64, "versions": {"sdk": "1.0.0", "ffmpeg": "test"}}
    monkeypatch.setattr(
        analyzer,
        "_prepare",
        lambda *_: (tmp_path / "derived.mp4", inputs["key"], dict(inputs["versions"])),
    )
    frames = tuple(Frame(i * 500, 64, 36, bytes([255]) * 2304) for i in range(4))
    monkeypatch.setattr(module, "decode_frames", lambda *_: frames)
    return analyzer, sid, inputs


def run(analyzer: Analyzer, sid: str, **params: Any) -> dict[str, Any]:
    return analyzer.run(
        {"session_id": sid, "profile_id": "generic-open-world", **params}, job_id=new_id("job")
    )


def events(analyzer: Analyzer, sid: str) -> list[dict[str, Any]]:
    with contextlib.closing(analyzer.database.connect()) as conn:
        return [normalize(e) for e in EventRepository(conn).list_for_session(sid)]


def test_manifest_errors_have_exact_paths() -> None:
    doc = manifest()
    doc["regions"]["signal"] = [0.9, 0, 0.5, 1]
    with pytest.raises(ProfileError, match=r"regions.signal"):
        ProfileCatalog().resolve(doc)
    doc = manifest()
    doc["locales"]["en"]["version"] = "unknown"
    with pytest.raises(ProfileError, match=r"locales.en.version"):
        ProfileCatalog().resolve(doc)


@pytest.mark.parametrize(
    "change, path",
    [
        ({"license": None}, "license"),
        ({"capabilities": ["python.exec"]}, "capabilities"),
        ({"surprise": True}, "surprise"),
    ],
)
def test_manifest_refuses_invalid_fields(change: dict[str, Any], path: str) -> None:
    with pytest.raises(ProfileError, match=path):
        ProfileCatalog().resolve({**manifest(), **change})


def test_inheritance_is_bounded_local_and_content_versioned(tmp_path: Path) -> None:
    base = manifest()
    write_profile(tmp_path, base)
    child = {
        "schema_version": "1.9",
        "id": "child",
        "profile_version": "1.0.0",
        "display_name": "Child",
        "extends": base["id"],
        "regions": {"other": [0, 0, 1, 1]},
    }
    write_profile(tmp_path, child)
    catalog = ProfileCatalog(tmp_path)
    first = catalog.load("child")
    assert set(first.document()["regions"]) == {"signal", "other"}
    base["locales"]["en"]["version"] = "1.0.1"
    write_profile(tmp_path, base)
    assert catalog.load("child").key != first.key
    child["extends"] = "child"
    write_profile(tmp_path, child)
    with pytest.raises(ProfileError, match="cycle"):
        catalog.load("child")
    for bad in ("../parent", "/parent", "parent/child", "https://example.com"):
        with pytest.raises(ProfileError):
            catalog.load(bad)
    for i in range(10):
        write_profile(
            tmp_path,
            {**manifest(), "id": f"level-{i}", **({"extends": f"level-{i + 1}"} if i < 9 else {})},
        )
    with pytest.raises(ProfileError, match="exceeds"):
        catalog.load("level-0")


@pytest.mark.parametrize("raw", ['{"id":"one","id":"two"}', '{"x":NaN}', "[]", '"x"', "{"])
def test_untrusted_json_refused(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "profile.json"
    path.write_text(raw)
    with pytest.raises(ProfileError):
        read_manifest(path)


def test_oversized_manifest_refused(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(b" " * (256 * 1024 + 1))
    with pytest.raises(ProfileError):
        read_manifest(path)


@pytest.mark.parametrize(
    "width,height,locale", [(32, 18, "en"), (100, 100, "en"), (1920, 1080, "fr")]
)
def test_compatibility_refuses_resolution_aspect_locale(
    width: int, height: int, locale: str
) -> None:
    with pytest.raises(AnalysisError, match=r"profile|frame|locales"):
        compatibility(manifest(), width, height, locale)


def test_temporal_example_cache_and_provenance(rig: tuple[Analyzer, str, dict[str, Any]]) -> None:
    analyzer, sid, _ = rig
    result = run(analyzer, sid)
    assert result["outcomes"][0]["status"] == "computed"
    event = events(analyzer, sid)[0]
    assert (event["start_ms"], event["end_ms"]) == (0, 2000)
    assert event["source"]["profile_version"] == "1.0.0"
    assert event["source"]["tool_versions"]["ffmpeg"] == "test"
    assert len(event["source"]["input_key"]) == 64
    assert event["evidence"][1]["frames"] == 4
    assert run(analyzer, sid)["outcomes"][0]["status"] == "cached"
    assert events(analyzer, sid) == [event]


@pytest.mark.parametrize("change", ["detector", "profile", "input", "tool", "locale"])
def test_cache_invalidation(
    rig: tuple[Analyzer, str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    analyzer, sid, inputs = rig
    run(analyzer, sid)
    old = events(analyzer, sid)[0]
    if change == "detector":
        monkeypatch.setattr(BrightRegion, "version", "1.0.1")
    elif change == "input":
        inputs["key"] = "b" * 64
    elif change == "tool":
        inputs["versions"]["ffmpeg"] = "new"
    else:
        doc = manifest()
        if change == "profile":
            doc["regions"]["signal"] = [0, 0, 1, 1]  # same version, different content
        else:
            doc["locales"]["en"]["version"] = "1.0.1"
        write_profile(analyzer.catalog.root, doc)
    assert run(analyzer, sid)["outcomes"][0]["status"] == "computed"
    new = events(analyzer, sid)
    assert len(new) == 1
    assert new[0]["id"] != old["id"]
    assert new[0]["source"]["input_key"] != old["source"]["input_key"]


def test_context_has_no_paths_and_is_immutable(rig: tuple[Analyzer, str, dict[str, Any]]) -> None:
    analyzer, sid, _ = rig

    class Inspector(BrightRegion):
        def setup(self, context: AnalysisContext) -> None:
            assert not hasattr(context, "path") and not hasattr(context, "database")
            with pytest.raises(TypeError):
                context.regions["signal"] = (0, 0, 1, 1)  # type: ignore[index]
            with pytest.raises(FrozenInstanceError):
                context.frames[0].source_ms = 10  # type: ignore[misc]
            with pytest.raises(TypeError):
                context.settings["confirmation_frames"] = 1  # type: ignore[index]
            assert isinstance(context.frames[0].pixels, bytes)

    analyzer.registry = {Inspector.id: Inspector}
    assert run(analyzer, sid)["outcomes"][0]["status"] == "computed"


def add_detector(analyzer: Analyzer, factory: Any) -> None:
    doc = manifest()
    doc["detectors"].append({"id": factory.id, "enabled": True})
    write_profile(analyzer.catalog.root, doc)
    analyzer.registry = {BrightRegion.id: BrightRegion, factory.id: factory}


@pytest.mark.parametrize(
    "stage", ["setup", "detect", "close", "factory", "evidence", "interval", "version"]
)
def test_failure_isolation_and_atomic_output(
    rig: tuple[Analyzer, str, dict[str, Any]], stage: str
) -> None:
    analyzer, sid, _ = rig

    class Broken(BrightRegion):
        id = "broken"
        version = "" if stage == "version" else "1.0.0"

        def __init__(self) -> None:
            if stage == "factory":
                raise RuntimeError("private path /Users/test/secret.mp4")

        def setup(self, context: AnalysisContext) -> None:
            if stage == "setup":
                raise RuntimeError("private path")

        def detect(self, context: AnalysisContext) -> Iterable[Detection]:
            for finding in super().detect(context):
                yield (
                    replace(finding, evidence=())
                    if stage == "evidence"
                    else replace(finding, end_ms=999999)
                    if stage == "interval"
                    else finding
                )
            if stage == "detect":
                raise RuntimeError("private path")

        def close(self) -> None:
            if stage == "close":
                raise RuntimeError("private path")

    add_detector(analyzer, Broken)
    result = run(analyzer, sid)
    assert [o["status"] for o in result["outcomes"]] == ["computed", "failed"]
    assert len(events(analyzer, sid)) == 1
    assert "private path" not in json.dumps(result)


def test_cancellation_keeps_completed_units_and_resumes(
    rig: tuple[Analyzer, str, dict[str, Any]],
) -> None:
    analyzer, sid, _ = rig
    cancel = threading.Event()
    cancelling = True

    class Interrupting(BrightRegion):
        id = "interrupting"

        def detect(self, context: AnalysisContext) -> Iterable[Detection]:
            if cancelling:
                cancel.set()
                context.check_cancelled()
            yield from super().detect(context)

    add_detector(analyzer, Interrupting)
    with pytest.raises(AnalysisCancelled):
        analyzer.run(
            {"session_id": sid, "profile_id": "generic-open-world"},
            job_id=new_id("job"),
            cancel=cancel,
        )
    assert len(events(analyzer, sid)) == 1
    cancelling = False
    cancel.clear()
    assert [o["status"] for o in run(analyzer, sid)["outcomes"]] == ["cached", "computed"]
    assert len(events(analyzer, sid)) == 2


def test_reviewed_events_survive_reanalysis(rig: tuple[Analyzer, str, dict[str, Any]]) -> None:
    analyzer, sid, _ = rig
    run(analyzer, sid)
    event_id = events(analyzer, sid)[0]["id"]
    with contextlib.closing(analyzer.database.connect()) as conn:
        EventRepository(conn).set_review_state(event_id, "confirmed")
        conn.commit()
    run(analyzer, sid, force=True)
    assert len(events(analyzer, sid)) == 2
    assert any(
        e["id"] == event_id and e["review_state"] == "confirmed" for e in events(analyzer, sid)
    )


def test_temporal_flicker_and_silence(
    rig: tuple[Analyzer, str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    analyzer, sid, _ = rig
    frames = tuple(
        Frame(i * 500, 64, 36, bytes([v]) * 2304) for i, v in enumerate([255, 0, 255, 0])
    )
    monkeypatch.setattr(module, "decode_frames", lambda *_: frames)
    assert run(analyzer, sid)["outcomes"][0]["event_ids"] == []
    assert events(analyzer, sid) == []


def test_pre_cancel_and_unknown_profile_fail_before_input(
    rig: tuple[Analyzer, str, dict[str, Any]],
) -> None:
    analyzer, sid, _ = rig
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AnalysisCancelled):
        analyzer.run({}, job_id=new_id("job"), cancel=cancel)
    doc = manifest()
    doc["detectors"][0]["id"] = "not-installed"
    write_profile(analyzer.catalog.root, doc)
    with pytest.raises(AnalysisError, match=r"detectors\[0\].id"):
        run(analyzer, sid)
    assert events(analyzer, sid) == []


def test_result_contract_rejects_unsupported_success() -> None:
    with pytest.raises(ValueError):
        load("analysis", {"schema_version": "1.9"})


def test_missing_cached_event_is_recomputed(rig: tuple[Analyzer, str, dict[str, Any]]) -> None:
    analyzer, sid, _ = rig
    run(analyzer, sid)
    with contextlib.closing(analyzer.database.connect()) as conn:
        conn.execute("DELETE FROM events")
        conn.commit()
    assert run(analyzer, sid)["outcomes"][0]["status"] == "computed"
    assert len(events(analyzer, sid)) == 1


def test_layout_invalidation_and_hidden_interval_clipping(
    rig: tuple[Analyzer, str, dict[str, Any]],
) -> None:
    analyzer, sid, _ = rig
    run(analyzer, sid)
    old_key = events(analyzer, sid)[0]["source"]["input_key"]
    with contextlib.closing(analyzer.database.connect()) as conn:
        aid = install(conn, [Clip("two.mp4", at(1))])[0]
        # Add a second member while preserving the first one's event.
        conn.execute(
            "INSERT INTO session_assets (session_id,asset_id,order_index,session_start_ms,"
            "trim_in_ms,overlap_with_previous_ms) VALUES (?,?,1,59000,0,1000)",
            (sid, aid),
        )
        conn.commit()
    assert [o["status"] for o in run(analyzer, sid)["outcomes"]] == ["computed", "computed"]
    current = events(analyzer, sid)
    assert current[0]["source"]["input_key"] != old_key
    assert (current[1]["start_ms"], current[1]["end_ms"]) == (60000, 61000)
    with contextlib.closing(analyzer.database.connect()) as conn:
        conn.execute(
            "UPDATE session_assets SET overlap_with_previous_ms=60000 WHERE asset_id=?", (aid,)
        )
        conn.commit()
    run(analyzer, sid)
    assert len(events(analyzer, sid)) == 1  # completely repeated clip emits no duplicate event


def test_correction_during_detection_refuses_obsolete_timing(
    rig: tuple[Analyzer, str, dict[str, Any]],
) -> None:
    analyzer, sid, _ = rig

    class Changing(BrightRegion):
        def detect(self, context: AnalysisContext) -> Iterable[Detection]:
            with contextlib.closing(analyzer.database.connect()) as conn:
                conn.execute("DELETE FROM session_assets WHERE session_id=?", (sid,))
                conn.commit()
            yield from super().detect(context)

    analyzer.registry = {Changing.id: Changing}
    assert run(analyzer, sid)["outcomes"][0]["error"]["code"] == "analysis.session_changed"
    assert events(analyzer, sid) == []


def test_incompatible_capability_skips_without_running_detector(
    rig: tuple[Analyzer, str, dict[str, Any]],
) -> None:
    analyzer, sid, _ = rig
    doc = manifest()
    doc["capabilities"] = []
    write_profile(analyzer.catalog.root, doc)
    assert run(analyzer, sid)["outcomes"][0]["status"] == "skipped"
    assert events(analyzer, sid) == []


def test_job_reports_partial_failure_without_losing_success(
    rig: tuple[Analyzer, str, dict[str, Any]],
) -> None:
    from fastapi.testclient import TestClient

    from openworld_moments.api.app import ApiSettings, create_app
    from openworld_moments.jobs.engine import JobEngine
    from openworld_moments.jobs.handlers import analyze_handler
    from tests.worker.conftest import wait_for

    analyzer, sid, _ = rig

    class Broken(BrightRegion):
        id = "broken"

        def setup(self, context: AnalysisContext) -> None:
            raise RuntimeError("private data")

    add_detector(analyzer, Broken)
    handler = analyze_handler(analyzer)
    engine = JobEngine(analyzer.database, {handler.kind: handler})
    settings = ApiSettings("a" * 64, frozenset({"testserver"}), require_loopback_peer=False)
    with TestClient(create_app(engine, settings)) as client:
        client.headers["Authorization"] = f"Bearer {settings.token}"
        response = client.post(
            f"/v1/sessions/{sid}/analyze", json={"profile_id": "generic-open-world"}
        )
        assert response.status_code == 201
        jid = response.json()["id"]
        wait_for(lambda: client.get(f"/v1/jobs/{jid}").json()["state"] == "failed")
        job = client.get(f"/v1/jobs/{jid}").json()
        assert job["error"]["code"] == "analysis.partial_failure"
        assert [o["status"] for o in job["result"]["outcomes"]] == ["computed", "failed"]
        assert len(client.get("/v1/events", params={"session_id": sid}).json()) == 1
        assert "private data" not in json.dumps(job)


def test_mixed_roi_and_whole_frame_detectors_cache_and_calibration(
    rig: tuple[Analyzer, str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from openworld_moments.detectors.calibration import Calibration
    from openworld_moments.detectors.inputs import ROI_SAMPLER_VERSION, SAMPLER_VERSION
    from openworld_moments.detectors.wanted import WantedState
    from openworld_moments.detectors.wanted_fixtures import DEFAULT_REGION, fixture_frame

    analyzer, sid, inputs = rig
    inputs["versions"]["sampler"] = SAMPLER_VERSION
    doc = manifest()
    doc["regions"]["wanted_indicator"] = list(DEFAULT_REGION)
    doc["detectors"].append({"id": WantedState.id, "enabled": True})
    write_profile(analyzer.catalog.root, doc)
    decoded: list[tuple[float, ...] | None] = []

    def whole(*_: Any) -> tuple[Frame, ...]:
        decoded.append(None)
        return tuple(Frame(i * 500, 64, 36, bytes([255]) * 2304) for i in range(6))

    def roi(_path: Any, _tool: Any, _cancel: Any, region: tuple[float, ...]) -> tuple[Frame, ...]:
        decoded.append(region)
        return tuple(
            fixture_frame(level, i * 500, region=region)
            for i, level in enumerate([0] * 3 + [2] * 3)
        )

    monkeypatch.setattr(module, "decode_frames", whole)
    monkeypatch.setattr(module, "decode_region", roi)
    result = run(analyzer, sid)
    assert [r["status"] for r in result["outcomes"]] == ["computed", "computed"]
    assert decoded == [None, DEFAULT_REGION]
    saved = events(analyzer, sid)
    assert {e["source"]["tool_versions"]["sampler"] for e in saved} == {
        SAMPLER_VERSION,
        ROI_SAMPLER_VERSION,
    }
    assert {e["source"]["detector_id"] for e in saved} == {BrightRegion.id, WantedState.id}
    assert [r["status"] for r in run(analyzer, sid)["outcomes"]] == ["cached", "cached"]
    assert decoded == [None, DEFAULT_REGION]
    calibration = Calibration(analyzer.database, analyzer.catalog)
    state = calibration.state(doc["id"])
    replacement = (0.2, 0.1, 0.6, 0.2)
    calibration.save(doc["id"], state["base_key"], {"wanted_indicator": list(replacement)})
    assert [r["status"] for r in run(analyzer, sid)["outcomes"]] == ["computed", "computed"]
    assert decoded[-1] == replacement


def test_roi_decode_cancellation_and_failure_keep_other_completed_units(
    rig: tuple[Analyzer, str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from openworld_moments.detectors.wanted import WantedState
    from openworld_moments.detectors.wanted_fixtures import DEFAULT_REGION
    from openworld_moments.media.process import ToolCancelled

    analyzer, sid, _ = rig
    doc = manifest()
    doc["regions"]["wanted_indicator"] = list(DEFAULT_REGION)
    doc["detectors"].append({"id": WantedState.id, "enabled": True})
    write_profile(analyzer.catalog.root, doc)

    def cancelled(*_: Any) -> Any:
        raise ToolCancelled("cancelled")

    monkeypatch.setattr(module, "decode_region", cancelled)
    with pytest.raises(AnalysisCancelled):
        run(analyzer, sid)
    old = events(analyzer, sid)
    assert len(old) == 1 and old[0]["source"]["detector_id"] == BrightRegion.id

    def broken(*_: Any) -> Any:
        raise AnalysisError("analysis.decode_failed", "Cannot decode ROI")

    monkeypatch.setattr(module, "decode_region", broken)
    result = run(analyzer, sid)
    assert [r["status"] for r in result["outcomes"]] == ["cached", "failed"]
    assert result["outcomes"][1]["error"]["code"] == "analysis.decode_failed"
    assert events(analyzer, sid) == old
