# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.media.tools import MediaTools
from openworld_moments.system import doctor, inventory


def test_runtime_inventory_detects_corruption_missing_tools_and_traversal(tmp_path: Path) -> None:
    names = ["owm-worker.exe", "tools/ffmpeg.exe", "tools/ffprobe.exe"]
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(b"runtime fixture")
    doc = {"files": {n: hashlib.sha256(b"runtime fixture").hexdigest() for n in names}}
    manifest = tmp_path / "inventory.json"
    manifest.write_text(json.dumps(doc))
    assert inventory(tmp_path) == doc
    (tmp_path / names[1]).write_bytes(b"corrupt runtime")
    with pytest.raises(ValueError, match="checksum"):
        inventory(tmp_path)
    (tmp_path / names[1]).write_bytes(b"runtime fixture")
    del doc["files"][names[2]]
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="incomplete"):
        inventory(tmp_path)
    doc["files"]["../escape"] = "a" * 64
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="path"):
        inventory(tmp_path)


def test_doctor_reports_failed_cpu_and_codecs_without_network(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from openworld_moments.render.encoders import EncoderProbe

    tools = MediaTools()
    monkeypatch.setattr(
        tools,
        "capabilities",
        lambda: {"probe_ready": False, "derived": {"ready": False}, "ffmpeg": {}, "ffprobe": {}},
    )
    monkeypatch.setattr(
        EncoderProbe, "status", lambda *_: [{"id": "libx264", "kind": "cpu", "available": False}]
    )
    report = doctor(tmp_path, tools)
    load("system-doctor", report)
    assert not report["ready"]
    assert any(c["id"] == "cpu-encode" and c["status"] == "fail" for c in report["checks"])
    assert any(c["id"] == "models" and c["status"] == "pass" for c in report["checks"])


def test_doctor_hardware_is_optional_when_cpu_works(tmp_path: Path, monkeypatch: Any) -> None:
    from openworld_moments.render.encoders import EncoderProbe

    tools = MediaTools()
    monkeypatch.setattr(
        tools,
        "capabilities",
        lambda: {"probe_ready": True, "derived": {"ready": True}, "ffmpeg": {}, "ffprobe": {}},
    )
    monkeypatch.setattr(
        EncoderProbe, "status", lambda *_: [{"id": "libx264", "kind": "cpu", "available": True}]
    )
    report = doctor(tmp_path, tools)
    load("system-doctor", report)
    assert report["ready"]
    assert any(c["id"] == "acceleration" and c["status"] == "warn" for c in report["checks"])
