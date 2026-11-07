# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.calibration import Calibration
from openworld_moments.detectors.profiles import (
    DEFAULT_CATALOG,
    ProfileCatalog,
    ProfileError,
    read_manifest,
)
from openworld_moments.detectors.service import Analyzer
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.media.tools import MediaTools
from openworld_moments.storage import Database

PID = "generic-open-world"


@pytest.fixture
def calibration(tmp_path: Path) -> Calibration:
    root = tmp_path / "catalog"
    path = root / PID / "profile.json"
    path.parent.mkdir(parents=True)
    path.write_bytes((DEFAULT_CATALOG / PID / "profile.json").read_bytes())
    return Calibration(
        Database.open(tmp_path / "library" / "database.sqlite3"), ProfileCatalog(root)
    )


def test_sparse_roundtrip_reset_restart_and_runtime(calibration: Calibration) -> None:
    service = calibration
    path = service.catalog.path(PID)
    before = path.read_bytes()
    state = service.state(PID)
    region = [0.2, 0.3, 0.4, 0.5]
    saved = service.save(PID, state["base_key"], {"signal": region, "extra": [0, 0, 1, 1]})
    assert saved["patch"]["regions"] == {"signal": region, "extra": [0, 0, 1, 1]}
    tools = MediaTools()
    analyzer = Analyzer(
        service.database, tools, DerivedMedia(service.database, tools), catalog=service.catalog
    )
    assert analyzer.profile(PID).document()["regions"]["signal"] == region
    assert analyzer.profile(PID).key != state["base_key"]
    patch = json.loads(json.dumps(saved["patch"]))  # export bytes, no frame/paths/assets
    assert set(patch) == {
        "schema_version",
        "profile_id",
        "base_version",
        "base_key",
        "game_family",
        "frame",
        "regions",
        "provenance",
    }
    service.reset(PID)
    assert analyzer.profile(PID).key == state["base_key"]
    service.import_patch(PID, patch)
    restarted = Calibration(Database.open(service.database.path), service.catalog)
    assert restarted.state(PID)["patch"] == patch
    reset = restarted.reset(PID)
    assert reset["patch"] is None and reset["effective"] == reset["base"] == state["base"]
    assert path.read_bytes() == before


def test_overrides_survive_profile_update_and_new_defaults(calibration: Calibration) -> None:
    s = calibration
    state = s.state(PID)
    s.save(PID, state["base_key"], {"signal": [0, 0, 0.5, 0.5]})
    doc = read_manifest(s.catalog.path(PID))
    doc["profile_version"] = "1.1.0"
    doc["regions"] = {"signal": [0.2, 0.2, 0.3, 0.3], "new-default": [0.8, 0.8, 0.1, 0.1]}
    s.catalog.path(PID).write_text(json.dumps(doc))
    updated = s.state(PID)
    assert updated["base_changed"] and updated["conflict"] is None
    assert updated["effective"]["regions"] == {
        "signal": [0, 0, 0.5, 0.5],
        "new-default": [0.8, 0.8, 0.1, 0.1],
    }
    assert updated["patch"]["base_version"] == "1.0.0"
    with pytest.raises(ProfileError, match="reload"):
        s.save(PID, state["base_key"], {})
    doc["frame"]["aspect_ratios"] = ["4:3"]
    s.catalog.path(PID).write_text(json.dumps(doc))
    assert s.state(PID)["conflict"]
    with pytest.raises(ProfileError, match="compatibility changed"):
        s.effective(PID)
    assert s.reset(PID)["effective"]["regions"] == doc["regions"]


@pytest.mark.parametrize(
    "regions",
    [
        {"signal": [0.9, 0, 0.2, 1]},
        {"signal": [0, 0.9, 1, 0.2]},
        {"signal": [0, 0, 0, 1]},
        {"signal": [float("nan"), 0, 1, 1]},
        {"../bad": [0, 0, 1, 1]},
        {"signal": [0, 0, 1]},
        {"a" * 129: [0, 0, 1, 1]},
    ],
)
def test_invalid_save_does_not_replace_saved_patch(
    calibration: Calibration, regions: dict[str, Any]
) -> None:
    s = calibration
    state = s.state(PID)
    good = s.save(PID, state["base_key"], {"signal": [0, 0, 0.5, 0.5]})["patch"]
    with pytest.raises(ProfileError):
        s.save(PID, state["base_key"], regions)
    assert s.patch(PID) == good


@pytest.mark.parametrize(
    "field,value",
    [
        ("frame_image", "data:image/png;base64,content"),
        ("game_family", "different"),
        ("profile_id", "different"),
        ("base_key", "bad"),
        ("schema_version", "999.0"),
    ],
)
def test_invalid_import_preserves_state(calibration: Calibration, field: str, value: Any) -> None:
    s = calibration
    state = s.state(PID)
    patch = s.save(PID, state["base_key"], {})["patch"]
    invalid = copy.deepcopy(patch)
    invalid[field] = value
    with pytest.raises(ProfileError):
        s.import_patch(PID, invalid)
    assert s.patch(PID) == patch


def test_authenticated_patch_export_import_reset_api_e2e(calibration: Calibration) -> None:
    s = calibration
    engine = JobEngine(s.database, {})
    settings = ApiSettings("test-token", frozenset({"testserver"}), require_loopback_peer=False)
    with TestClient(create_app(engine, settings, profile_catalog=s.catalog)) as c:
        url = f"/v1/profiles/{PID}/calibration"
        assert c.get(url).status_code == 401
        c.headers["Authorization"] = "Bearer test-token"
        assert c.get("/v1/profiles").json()[0]["id"] == PID
        state = c.get(url).json()
        assert (
            c.put(
                url,
                json={"base_key": state["base_key"], "regions": {"signal": [0.1, 0.2, 0.3, 0.4]}},
            ).status_code
            == 200
        )
        # Export is the same saved, validated patch the host writes through its save dialog.
        exported = json.loads(json.dumps(c.get(url).json()["patch"]))
        assert c.post(f"/v1/profiles/{PID}/reset").json()["patch"] is None
        imported = c.post(f"/v1/profiles/{PID}/patch", json=exported)
        assert imported.status_code == 200 and imported.json()["patch"] == exported
        assert (
            c.put(
                url, json={"base_key": state["base_key"], "regions": {"signal": [0.9, 0, 1, 1]}}
            ).status_code
            == 422
        )
        assert c.get(url).json()["patch"] == exported
        assert c.post(f"/v1/profiles/{PID}/reset").json()["effective"] == state["base"]


def test_ephemeral_sdk_preview_validates_and_never_saves(calibration: Calibration) -> None:
    s = calibration
    state = s.state(PID)
    preview = s.preview(PID, state["base_key"], {"signal": [0, 0, 1, 1]}, [255] * 2304, 1000)
    assert preview["available"] and preview["detections"] == []
    assert preview["confirmation_frames"] == 3 and s.patch(PID) is None
    # Temporal rules remain intact: one frame cannot invent three observations.
    doc = read_manifest(s.catalog.path(PID))
    doc["detectors"][0]["confirmation_frames"] = 1
    s.catalog.path(PID).write_text(json.dumps(doc))
    key = s.state(PID)["base_key"]
    preview = s.preview(PID, key, {}, [255] * 2304, 1000)
    assert preview["detections"][0]["start_ms"] == 1000
    assert preview["detections"][0]["confidence"] == 0.95
    assert s.preview(PID, key, {}, [0] * 2304, 1000)["detections"] == []
    with pytest.raises(ProfileError):
        s.preview(PID, key, {}, [255], 0)
    with pytest.raises(ProfileError):
        s.preview(PID, key, {"signal": [0.9, 0, 1, 1]}, [255] * 2304, 0)
    doc["detectors"] = []
    s.catalog.path(PID).write_text(json.dumps(doc))
    assert not s.preview(PID, s.state(PID)["base_key"], {}, [0] * 2304, 0)["available"]


def test_preview_api_bounds_and_read_only_state(calibration: Calibration) -> None:
    s = calibration
    settings = ApiSettings("token", frozenset({"testserver"}), require_loopback_peer=False)
    with TestClient(
        create_app(JobEngine(s.database, {}), settings, profile_catalog=s.catalog)
    ) as c:
        c.headers["Authorization"] = "Bearer token"
        state = s.state(PID)
        body = {"base_key": state["base_key"], "regions": {}, "gray": [255] * 2304, "source_ms": 0}
        route = f"/v1/profiles/{PID}/preview"
        assert c.post(route, json=body).json()["detections"] == []
        for bad in [
            {**body, "gray": [255] * 2303},
            {**body, "gray": [256] * 2304},
            {**body, "gray": [True] * 2304},
            {**body, "source_ms": -1},
        ]:
            assert c.post(route, json=bad).status_code == 422
        assert s.patch(PID) is None


def test_patch_count_and_size_boundaries_preserve_previous_state(calibration: Calibration) -> None:
    s = calibration
    key = s.state(PID)["base_key"]
    regions = {f"r-{i}": [0, 0, 0.5, 0.5] for i in range(128)}
    good = s.save(PID, key, regions)["patch"]
    with pytest.raises(ProfileError):
        s.save(PID, key, {**regions, "one-too-many": [0, 0, 1, 1]})
    with pytest.raises(ProfileError, match="64 KiB"):
        s.import_patch(PID, {**good, "frame_image": "x" * 65536})
    assert s.patch(PID) == good
