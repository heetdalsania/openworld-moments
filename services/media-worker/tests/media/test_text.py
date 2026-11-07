# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import pytest
from openworld_moments_contracts import load

from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.calibration import Calibration
from openworld_moments.detectors.ocr import Tesseract
from openworld_moments.detectors.sdk import AnalysisError
from openworld_moments.detectors.service import Analyzer
from openworld_moments.detectors.text import CATEGORIES, classify
from openworld_moments.detectors.text_fixtures import BANNER_REGION, canvas, frame
from openworld_moments.ids import new_id
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from tests.detectors.test_text import VOCABULARY
from tests.media.test_wanted import imported, observations


@pytest.fixture(scope="module")
def ocr() -> Tesseract:
    backend = Tesseract()
    try:
        backend.prepare("eng", threading.Event())
    except AnalysisError as exc:
        if os.environ.get("OWM_REQUIRE_OCR") == "1":
            pytest.fail(exc.message + " (OWM_REQUIRE_OCR=1)")
        pytest.skip(exc.message)
    return backend


@pytest.mark.parametrize("category", list(CATEGORIES))
@pytest.mark.parametrize("variant", ["base", "small", "contrast", "outline", "duplex", "multiline"])
def test_real_ocr_stylized_variants(ocr: Tesseract, category: str, variant: str) -> None:
    text = VOCABULARY[category][0]
    if variant == "multiline" and " " in text:
        text = text.replace(" ", "\n", 1)
    sample = frame(
        text,
        scale=0.8 if variant == "small" else 1.1,
        contrast=90 if variant == "contrast" else 220,
        outline=variant == "outline",
        style="duplex" if variant == "duplex" else "simplex",
    )
    result = ocr.read(sample, "contrast", threading.Event())
    assert classify(result.text, VOCABULARY, 0.9)[0] == category, (variant, text, result)
    assert result.score >= 0.75, (variant, text, result)
    assert all(BANNER_REGION[0] <= line.region[0] < 1 for line in result.lines)


def generate(
    root: Path,
    ffmpeg: ToolInfo,
    width: int,
    height: int,
    crf: int,
    brightness: float,
    outline: bool,
    region: tuple[float, ...] = BANNER_REGION,
) -> Path:
    a = "MORGAN: MEET AT BRIDGE\nBRING THE BLUE CASE"
    b = "WAIT BY THE RIVER"
    sequence = (
        [("", "")] * 2
        + [("TASK COMPLETE", a)] * 4
        + [("TASK COMPLETE", b)] * 2
        + [("BLUE UMBRELLA", b)] * 2
        + [("CAUGHT", "")] * 4
        + [("", "")] * 2
    )
    pictures = {
        pair: canvas(
            width, height, *pair, brightness=brightness, outline=outline, banner_region=region
        )
        for pair in set(sequence)
    }
    raw = root / "text.gray"
    with raw.open("wb") as stream:
        for pair in sequence:
            stream.write(pictures[pair])
    clip = root / "Synthetic text café 字幕.mp4"
    result = run_tool(
        [
            *ffmpeg.command,
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


@pytest.mark.parametrize(
    "size,crf,brightness,outline",
    [
        ((1280, 720), 18, 1, False),
        ((1920, 1080), 30, 0.7, True),
        ((3840, 2160), 32, 1, False),
    ],
)
def test_real_media_ocr_intervals_cache_provenance_and_source_preservation(
    tmp_path: Path,
    tools: MediaTools,
    ffmpeg: ToolInfo,
    ocr: Tesseract,
    size: tuple[int, int],
    crf: int,
    brightness: float,
    outline: bool,
) -> None:
    clip = generate(tmp_path, ffmpeg, *size, crf, brightness, outline)
    before = hashlib.sha256(clip.read_bytes()).hexdigest()
    mtime = clip.stat().st_mtime_ns
    db, sid, _ = imported(tmp_path, tools, clip)
    analyzer = Analyzer(db, tools, DerivedMedia(db, tools))
    params = {"session_id": sid, "profile_id": "generic-text"}
    result = analyzer.run(params, job_id=new_id("job"))
    assert all(o["status"] == "computed" for o in result["outcomes"]), result
    events = observations(db, sid)
    assert sorted(e["type"] for e in events) == sorted(
        [
            "openworld.mission_completed",
            "openworld.ocr_text",
            "openworld.arrest",
            "openworld.subtitle",
            "openworld.subtitle",
        ]
    ), events
    by_type = {e["type"]: e for e in events}
    assert by_type["openworld.mission_completed"]["attributes"]["spoiler_risk"] is True
    assert by_type["openworld.ocr_text"]["confidence"] <= 0.49
    subtitles = sorted(
        (e for e in events if e["type"] == "openworld.subtitle"), key=lambda e: e["start_ms"]
    )
    assert [(e["start_ms"], e["end_ms"]) for e in subtitles] == [(1000, 3000), (3000, 5000)]
    assert subtitles[0]["attributes"]["speaker"] == "MORGAN"
    assert len(subtitles[0]["evidence"][0]["lines"]) == 2
    for event in events:
        load("event", event)
        versions = event["source"]["tool_versions"]
        assert versions["ocr_engine"].startswith("tesseract-")
        assert len(versions["ocr_model_sha256"]) == 64 and versions["ocr_locale_version"] == "1.0.0"
        assert versions["ocr_locale"] == "en"
        assert versions["sampler"] == "gray-roi640x128-2fps-v1"
        assert event["start_ms"] <= event["evidence"][0]["frame_ms"] < event["end_ms"]
    cached = analyzer.run(params, job_id=new_id("job"))
    assert all(o["status"] == "cached" for o in cached["outcomes"])
    assert [o["event_ids"] for o in cached["outcomes"]] == [
        o["event_ids"] for o in result["outcomes"]
    ]
    assert (
        hashlib.sha256(clip.read_bytes()).hexdigest() == before and clip.stat().st_mtime_ns == mtime
    )


def test_local_calibration_and_false_region(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo, ocr: Tesseract
) -> None:
    region = (0.1, 0.45, 0.8, 0.24)
    clip = generate(tmp_path, ffmpeg, 1280, 720, 23, 1, False, region)
    db, sid, _ = imported(tmp_path, tools, clip)
    analyzer = Analyzer(db, tools, DerivedMedia(db, tools))
    params = {"session_id": sid, "profile_id": "generic-text"}
    analyzer.run(params, job_id=new_id("job"))
    events = observations(db, sid)
    assert all(e["source"]["detector_id"] != "region-banner-ocr" for e in events)
    calibration = Calibration(db)
    state = calibration.state("generic-text")
    calibration.save("generic-text", state["base_key"], {"mission_banner": list(region)})
    result = analyzer.run(params, job_id=new_id("job"))
    assert result["outcomes"][0]["status"] == "computed"
    assert len(result["outcomes"][0]["event_ids"]) == 3


def test_missing_ocr_skips_only_ocr_units(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = generate(tmp_path, ffmpeg, 1280, 720, 23, 1, False)
    db, sid, _ = imported(tmp_path, tools, clip)
    monkeypatch.setenv("OWM_TESSERACT", str(tmp_path / "missing-tool"))
    result = Analyzer(db, tools, DerivedMedia(db, tools)).run(
        {"session_id": sid, "profile_id": "generic-text"}, job_id=new_id("job")
    )
    assert [o["status"] for o in result["outcomes"]] == ["skipped", "skipped"]
    assert all(
        o["error"]["code"] == "ocr.unavailable" and o["event_ids"] == [] for o in result["outcomes"]
    )


def test_real_ocr_job_api_and_cli(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo, ocr: Tesseract
) -> None:
    import json
    import subprocess
    import sys

    from fastapi.testclient import TestClient

    from openworld_moments.api.app import ApiSettings, create_app
    from openworld_moments.jobs.engine import JobEngine
    from openworld_moments.jobs.handlers import build_handlers
    from tests.worker.conftest import wait_for

    clip = generate(tmp_path, ffmpeg, 1280, 720, 23, 1, False)
    db, sid, _ = imported(tmp_path, tools, clip)
    derived = DerivedMedia(db, tools)
    engine = JobEngine(db, build_handlers(tools, database=db, derived=derived))
    settings = ApiSettings("local-token", frozenset({"testserver"}), require_loopback_peer=False)
    with TestClient(create_app(engine, settings, derived=derived)) as client:
        client.headers["Authorization"] = "Bearer local-token"
        response = client.post(f"/v1/sessions/{sid}/analyze", json={"profile_id": "generic-text"})
        assert response.status_code == 201
        jid = response.json()["id"]
        wait_for(lambda: client.get(f"/v1/jobs/{jid}").json()["state"] in ("ready", "failed"))
        job = client.get(f"/v1/jobs/{jid}").json()
        assert job["state"] == "ready", job
        assert len(client.get("/v1/events", params={"session_id": sid}).json()) == 5
    for arguments, expected in [(["doctor"], 0), (["benchmark", "--samples", "0"], 1)]:
        command = subprocess.run(  # noqa: S603 - fixed executable and argument array
            [sys.executable, "-m", "openworld_moments.detectors", "text", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert command.returncode == expected, command.stdout + command.stderr
        result = json.loads(command.stdout)
        if expected == 0:
            assert result["available"] and "ocr_model_sha256" in result["tool_versions"]
        else:
            assert result["error"]["code"] == "ocr.invalid_benchmark"
