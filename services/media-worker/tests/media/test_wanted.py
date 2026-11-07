# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.calibration import Calibration
from openworld_moments.detectors.inputs import ROI_SAMPLER_VERSION, decode_region
from openworld_moments.detectors.profiles import ProfileCatalog
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.detectors.service import Analyzer
from openworld_moments.detectors.wanted_fixtures import DEFAULT_REGION, canvas_pixels
from openworld_moments.detectors.wanted_replay import replay
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.process import ToolCancelled, run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import (
    AssetRepository,
    Database,
    DerivedArtifactRepository,
    EventRepository,
)
from tests.worker.conftest import wait_for


def generate(
    root: Path,
    tool: ToolInfo,
    width: int,
    height: int,
    *,
    crf: int = 28,
    region: tuple[float, ...] = DEFAULT_REGION,
    brightness: float = 1,
) -> Path:
    raw = root / "row.gray"
    pixels = {
        level: canvas_pixels(width, height, level, region=region, brightness=brightness)
        for level in (0, 2, 5)
    }
    with raw.open("wb") as stream:
        for level in [0] * 6 + [2] * 6 + [5] * 6 + [0] * 6:
            stream.write(pixels[level])
    clip = root / "Wanted synthetic café 指標.mp4"
    result = run_tool(
        [
            *tool.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "gray",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            "2",
            "-i",
            str(raw),
            "-vf",
            "fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        timeout_s=120,
    )
    assert result.returncode == 0, result.stderr_tail
    raw.unlink()
    return clip


def imported(root: Path, tools: MediaTools, clip: Path) -> tuple[Database, str, str]:
    db = Database.open(root / "library" / "database.sqlite3")
    Importer(db, tools).run_import(
        {"paths": [str(clip)], "mode": "reference"},
        job_id=new_id("job"),
        cancel=threading.Event(),
        progress=lambda *_: None,
    )
    sessions = SessionService(db)
    sessions.recompute({})
    with contextlib.closing(db.connect()) as conn:
        sid = sessions.list_docs(conn, limit=1, offset=0)[0]["id"]
        aid = AssetRepository(conn).query(limit=1)[0].id
    return db, sid, aid


def observations(db: Database, sid: str) -> list[dict[str, Any]]:
    from openworld_moments_contracts import normalize

    with contextlib.closing(db.connect()) as conn:
        return [normalize(e) for e in EventRepository(conn).list_for_session(sid)]


@pytest.mark.parametrize(
    "size,crf,brightness", [((1280, 720), 18, 1), ((1920, 1080), 32, 0.7), ((3840, 2160), 38, 1)]
)
def test_source_scale_brightness_compression_and_full_analyzer(
    tmp_path: Path,
    tools: MediaTools,
    ffmpeg: ToolInfo,
    size: tuple[int, int],
    crf: int,
    brightness: float,
) -> None:
    clip = generate(tmp_path, ffmpeg, *size, crf=crf, brightness=brightness)
    with clip.open("rb") as stream:
        before = hashlib.file_digest(stream, "sha256").hexdigest()
    mtime = clip.stat().st_mtime_ns
    db, sid, aid = imported(tmp_path, tools, clip)
    analyzer = Analyzer(db, tools, DerivedMedia(db, tools))
    result = analyzer.run({"session_id": sid, "profile_id": "generic-wanted"}, job_id=new_id("job"))
    if result["outcomes"][0]["status"] != "computed":
        with contextlib.closing(db.connect()) as conn:
            proxy = DerivedArtifactRepository(conn).get(aid, "proxy")
        pytest.fail(
            json.dumps(
                {"analysis": result, "proxy_error": proxy.last_error if proxy else None},
                indent=2,
            )
        )
    events = observations(db, sid)
    assert [(e["attributes"]["from"], e["attributes"]["to"]) for e in events] == [
        (0, 2),
        (2, 5),
        (5, 0),
    ], events
    for event in events:
        load("event", event)
        assert event["source"]["tool_versions"]["sampler"] == ROI_SAMPLER_VERSION
        assert event["evidence"][0]["frame_ms"] == event["attributes"]["confirmed_at_ms"]
        assert event["attributes"]["compatibility"] == "unvalidated"
    cached = analyzer.run({"session_id": sid, "profile_id": "generic-wanted"}, job_id=new_id("job"))
    assert cached["outcomes"][0]["event_ids"] == result["outcomes"][0]["event_ids"]
    assert cached["outcomes"][0]["status"] == "cached"
    with clip.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == before
    assert clip.stat().st_mtime_ns == mtime


def test_calibrated_hud_scale_replay_crops_and_api(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo
) -> None:
    region = (0.3, 0.4, 0.3375, 0.12)  # 75% HUD scale and a different location; same 5:1 row shape.
    clip = generate(tmp_path, ffmpeg, 1280, 720, region=region)
    db, sid, aid = imported(tmp_path, tools, clip)
    derived = DerivedMedia(db, tools)
    analyzer = Analyzer(db, tools, derived)
    params = {"session_id": sid, "profile_id": "generic-wanted"}
    initial = analyzer.run(params, job_id=new_id("job"))
    assert not initial["outcomes"][0]["event_ids"]
    calibration = Calibration(db)
    state = calibration.state("generic-wanted")
    calibration.save("generic-wanted", state["base_key"], {"wanted_indicator": list(region)})
    result = analyzer.run(params, job_id=new_id("job"))
    assert (
        result["outcomes"][0]["status"] == "computed"
        and len(result["outcomes"][0]["event_ids"]) == 3
    )
    report = replay(
        aid,
        tmp_path / "library",
        "generic-wanted",
        ProfileCatalog(),
        tmp_path / "report",
        crops=True,
    )
    trace = [
        json.loads(line) for line in (tmp_path / "report" / "trace.jsonl").read_text().splitlines()
    ]
    assert len(report["events"]) == 3 and report["samples"] == 24
    assert [(r["observed"], r["stable"]) for r in trace[4:7]] == [(0, 0), (0, 0), (2, 0)]
    for row in trace:
        if "crop_ref" in row:
            assert (
                (tmp_path / "report" / row["crop_ref"])
                .read_bytes()
                .startswith(b"P5\n200 40\n255\n")
            )
    assert "pixels" not in json.dumps(report) and str(tmp_path) not in json.dumps(report)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises((AnalysisCancelled, ToolCancelled)):
        replay(
            aid,
            tmp_path / "library",
            "generic-wanted",
            ProfileCatalog(),
            tmp_path / "cancelled",
            cancel=cancelled,
        )
    assert not (tmp_path / "cancelled").exists()
    engine = JobEngine(db, build_handlers(tools, database=db, derived=derived))
    settings = ApiSettings("local-token", frozenset({"testserver"}), require_loopback_peer=False)
    with TestClient(create_app(engine, settings, derived=derived)) as client:
        client.headers["Authorization"] = "Bearer local-token"
        response = client.post(
            f"/v1/sessions/{sid}/analyze", json={"profile_id": "generic-wanted", "force": True}
        )
        assert response.status_code == 201
        jid = response.json()["id"]
        wait_for(lambda: client.get(f"/v1/jobs/{jid}").json()["state"] in ("ready", "failed"))
        assert client.get(f"/v1/jobs/{jid}").json()["state"] == "ready"
        assert len(client.get("/v1/events", params={"session_id": sid}).json()) == 3
    command = subprocess.run(  # noqa: S603 - fixed executable, argument array
        [
            sys.executable,
            "-m",
            "openworld_moments.detectors",
            "wanted",
            "replay",
            aid,
            "--library",
            str(tmp_path / "library"),
            "--output",
            str(tmp_path / "cli-report"),
            "--crops",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert command.returncode == 0, command.stdout + command.stderr
    assert json.loads(command.stdout)["complete"]


@pytest.mark.parametrize("region", [(float("nan"), 0, 1, 1), (0.9, 0, 1, 1), (0, 0, 0, 1)])
def test_region_decoder_rejects_hostile_numbers_before_ffmpeg(
    tmp_path: Path, ffmpeg: ToolInfo, region: tuple[float, ...]
) -> None:
    from openworld_moments.detectors.sdk import AnalysisError

    with pytest.raises(AnalysisError):
        decode_region(tmp_path / "absent.mp4", ffmpeg, threading.Event(), region)


def test_compressed_unrelated_picture_is_unknown_and_cli_failures_are_safe(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo
) -> None:
    clip = tmp_path / "unrelated.mp4"
    result = run_tool(
        [
            *ffmpeg.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1280x720:r=30:d=3",
            "-c:v",
            "libx264",
            "-crf",
            "35",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        timeout_s=60,
    )
    assert result.returncode == 0
    _db, _, aid = imported(tmp_path, tools, clip)
    report = replay(
        aid, tmp_path / "library", "generic-wanted", ProfileCatalog(), tmp_path / "trace"
    )
    assert report["events"] == []
    rows = [json.loads(r) for r in (tmp_path / "trace" / "trace.jsonl").read_text().splitlines()]
    assert all(row["observed"] is None for row in rows)
    from openworld_moments.detectors.sdk import AnalysisError

    with pytest.raises(AnalysisError, match="new report directory"):
        replay(aid, tmp_path / "library", "generic-wanted", ProfileCatalog(), tmp_path / "trace")
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "openworld_moments.detectors",
            "wanted",
            "benchmark",
            "--seconds",
            "0",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert (
        command.returncode == 1
        and json.loads(command.stdout)["error"]["code"] == "wanted.invalid_benchmark"
    )
