# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render engine through real FFmpeg (M24). Golden projects: single segment,
multi-segment with a silent clip, manual crop keyframes and a privacy blur,
mute/gain, a Unicode path and a project without audio, each within 100 ms of its
target. Failure paths: cancellation, hardware encoder failure with an explicit CPU
fallback, disk full, validation failure (empty, truncated, black), changed sources
and text refusal. Plus the FFprobe audit, job/API surface and source preservation.
All media is generated."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived.service import DerivedMedia
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.projects.service import ManualProject, ProjectService, SaveProject
from openworld_moments.render.encoders import ENCODERS, EncoderSpec
from openworld_moments.render.plan import RenderError
from openworld_moments.render.service import RenderCancelled, Renderer, RenderFailed
from openworld_moments.render.validate import validate_output
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database
from tests.worker.conftest import wait_for

TOLERANCE_MS = 100


def make_clip(
    ffmpeg: ToolInfo, path: Path, picture: str, seconds: float, *, tone: int | None
) -> Path:
    joiner = ":" if "=" in picture else "="
    args = ["-f", "lavfi", "-i", f"{picture}{joiner}size=640x360:rate=30:duration={seconds}"]
    if tone is not None:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}"]
    result = run_tool(
        [
            *ffmpeg.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            *args,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            *(["-c:a", "aac"] if tone is not None else ["-an"]),
            str(path),
        ],
        timeout_s=120,
    )
    assert result.returncode == 0, result.stderr_tail
    return path


class Studio:
    def __init__(self, root: Path, tools: MediaTools) -> None:
        self.root, self.tools = root, tools
        self.database = Database.open(root / "library" / "database.sqlite3")
        self.projects = ProjectService(self.database)
        self.renderer = Renderer(self.database, tools)

    def project(self, *clips: Path, start_ms: int = 0, trim_end_ms: int = 0) -> str:
        Importer(self.database, self.tools).run_import(
            {"paths": [str(c) for c in clips], "mode": "reference"},
            job_id=new_id("job"),
            cancel=threading.Event(),
            progress=lambda *_: None,
        )
        SessionService(self.database).recompute({})
        with contextlib.closing(self.database.connect()) as conn:
            sessions = SessionService(self.database).list_docs(conn, limit=10, offset=0)
        assert len(sessions) == 1
        sid = sessions[0]["id"]
        selection = self.projects.selection(sid)
        state = self.projects.create(
            sid,
            ManualProject(
                title="Golden",
                layout_key=selection["layout_key"],
                start_ms=start_ms,
                end_ms=selection["duration_ms"] - trim_end_ms,
            ),
        )
        return str(state["document"]["project"]["id"])

    def edit(self, project_id: str, change: Any) -> None:
        state = self.projects.get(project_id)
        document = copy.deepcopy(state["document"])
        change(document["project"])
        self.projects.save(
            project_id, SaveProject(expected_revision=state["revision"], document=document)
        )

    def render(self, project_id: str, **params: Any) -> dict[str, Any]:
        return self.renderer.run(
            {"project_id": project_id, "preset_id": "horizontal-720p30", **params},
            job_id=new_id("job"),
            cancel=params.pop("cancel", None) if "cancel" in params else None,
        )

    def output(self, record: dict[str, Any]) -> Path:
        path: Path = self.renderer.root / record["output"]["relative_path"]
        return path


@pytest.fixture
def studio(tmp_path: Path, tools: MediaTools) -> Studio:
    return Studio(tmp_path, tools)


def digest(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def loudness(ffmpeg: ToolInfo, path: Path, start_s: float, seconds: float) -> float:
    result = run_tool(
        [
            *ffmpeg.command,
            "-hide_banner",
            "-nostdin",
            "-ss",
            f"{start_s}",
            "-t",
            f"{seconds}",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        timeout_s=60,
    )
    match = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", result.stderr_tail)
    assert match, result.stderr_tail
    return -200.0 if match[1] == "-inf" else float(match[1])


def assert_ready(record: dict[str, Any], target_ms: int) -> None:
    load("render", record)
    assert record["status"] == "ready", record.get("error")
    assert record["validation"]["passed"], record["validation"]
    assert abs(record["validation"]["probe"]["duration_ms"] - target_ms) <= TOLERANCE_MS
    assert record["plan"]["duration_ms"] == target_ms


def test_golden_single_segment_is_exact_validated_and_preserves_the_source(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "single.mp4", "testsrc2", 5, tone=440)
    before = digest(clip)
    pid = studio.project(clip, start_ms=700, trim_end_ms=300)
    record = studio.render(pid)
    assert_ready(record, 4000)
    output = studio.output(record)
    assert output.is_file() and record["output"]["size_bytes"] == output.stat().st_size
    assert hashlib.sha256(output.read_bytes()).hexdigest() == record["output"]["sha256"]
    manifest = json.loads(
        (studio.renderer.root / record["output"]["manifest_relative_path"]).read_text()
    )
    load("export-manifest", manifest)
    assert manifest["segments"] == [{"source": 0, "in_ms": 700, "out_ms": 4700}]
    assert str(tmp_path) not in json.dumps(manifest) and str(tmp_path) not in json.dumps(record)
    probe = record["validation"]["probe"]
    assert probe["video"]["codec"] == "h264" and probe["video"]["profile"] == "High"
    assert (probe["video"]["width"], probe["video"]["height"]) == (1280, 720)
    assert probe["audio"] == {"codec": "aac", "channels": 2, "sample_rate_hz": 48000}
    assert set(probe["tags"]) <= {"major_brand", "minor_version", "compatible_brands", "encoder"}
    assert digest(clip) == before
    assert studio.renderer.for_project(pid)[0]["id"] == record["id"]
    staging = studio.renderer.root / "staging" / "renders"
    assert not staging.exists() or not any(staging.iterdir())


def test_golden_multi_segment_with_silent_clip_crop_keyframes_and_blur(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    a = make_clip(ffmpeg, tmp_path / "a.mp4", "testsrc2", 3, tone=440)
    b = make_clip(ffmpeg, tmp_path / "b.mp4", "smptebars", 2.5, tone=None)
    pid = studio.project(a, b)

    def change(project: dict[str, Any]) -> None:
        first = project["tracks"][0]["segments"][0]
        first["crop"] = {
            "mode": "manual",
            "keyframes": [
                {"at_ms": 0, "region": [0, 0, 0.5, 0.5]},
                {"at_ms": 1500, "region": [0.5, 0.5, 0.5, 0.5]},
            ],
        }
        project["overlays"] = [
            {"kind": "blur", "start_ms": 0, "end_ms": 4000, "region": [0, 0, 0.25, 0.1]}
        ]

    studio.edit(pid, change)
    record = studio.render(pid)
    target = sum(s["out_ms"] - s["in_ms"] for s in record["plan"]["segments"])
    assert_ready(record, target)
    assert len(record["plan"]["segments"]) == 3  # the keyframe splits the first clip
    assert record["plan"]["output"]["audio"] is True
    # Silence was generated for the clip without audio, keeping the track continuous.
    out = studio.output(record)
    assert loudness(ffmpeg, out, (target - 1500) / 1000, 1.0) < -80
    assert loudness(ffmpeg, out, 0.5, 1.0) > -40


def test_golden_mute_and_gain(studio: Studio, ffmpeg: ToolInfo, tmp_path: Path) -> None:
    clip = make_clip(ffmpeg, tmp_path / "tone.mp4", "testsrc2", 6, tone=440)
    pid = studio.project(clip)
    reference = studio.render(pid)
    base = loudness(ffmpeg, studio.output(reference), 4.5, 1.0)

    def change(project: dict[str, Any]) -> None:
        project["audio"] = {
            "gain_db": -6,
            "gain_ranges": [{"start_ms": 2000, "end_ms": 4000, "gain_db": 6}],
            "mute_ranges": [{"start_ms": 500, "end_ms": 1500}],
        }

    studio.edit(pid, change)
    record = studio.render(pid)
    assert_ready(record, 6000)
    out = studio.output(record)
    assert loudness(ffmpeg, out, 0.7, 0.6) < -80  # muted
    assert loudness(ffmpeg, out, 4.5, 1.0) == pytest.approx(base - 6, abs=1.0)  # project gain
    assert loudness(ffmpeg, out, 2.5, 1.0) == pytest.approx(base + 6, abs=1.0)  # range override


def test_golden_unicode_path_and_no_audio_project(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    folder = tmp_path / "Captures — 日本語 & 'quotes'"
    folder.mkdir()
    clip = make_clip(ffmpeg, folder / "クリップ é 🎮.mp4", "smptebars", 3, tone=None)
    before = digest(clip)
    pid = studio.project(clip)
    record = studio.render(pid)
    assert_ready(record, 3000)
    assert record["plan"]["output"]["audio"] is False
    assert record["validation"]["probe"]["audio_streams"] == 0
    assert "audio" not in record["validation"]["probe"]
    assert record["plan"]["sources"][0]["original_name"] == "クリップ é 🎮.mp4"
    assert digest(clip) == before


def test_cancellation_leaves_nothing_marked_complete(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "long.mp4", "testsrc2", 20, tone=440)
    pid = studio.project(clip)
    cancel = threading.Event()
    job = new_id("job")

    def progress(done: int, total: int, message: str) -> None:
        if message == "Rendering" and done > 60:
            cancel.set()

    with pytest.raises(RenderCancelled):
        studio.renderer.run(
            {"project_id": pid, "preset_id": "horizontal-1080p30"},
            job_id=job,
            cancel=cancel,
            progress=progress,
        )
    record = studio.renderer.get(job)
    assert record["status"] == "cancelled" and record["error"]["code"] == "render.cancelled"
    assert "output" not in record
    renders = studio.renderer.root / "renders"
    assert not renders.exists() or not any(renders.rglob("*.mp4"))
    assert not (studio.renderer.root / "staging" / "renders" / job).exists()


def test_hardware_failure_offers_an_explicit_cpu_fallback(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "hw.mp4", "testsrc2", 2, tone=440)
    pid = studio.project(clip)
    # A "hardware" encoder that fails mid-render (an impossible x264 profile).
    broken = EncoderSpec(
        "h264_nvenc", "NVIDIA NVENC", "hardware", "libx264", "NVENC note.", ("-profile:v", "nope")
    )

    class Probe:
        def status(self, tool: ToolInfo, *, refresh: bool = False) -> list[dict[str, Any]]:
            return [
                {"id": "libx264", "label": "CPU (libx264)", "kind": "cpu", "available": True},
                {
                    "id": "h264_nvenc",
                    "label": "NVIDIA NVENC",
                    "kind": "hardware",
                    "available": True,
                },
            ]

    renderer = Renderer(
        studio.database,
        studio.tools,
        probe=Probe(),  # type: ignore[arg-type]
        encoders={"libx264": ENCODERS["libx264"], "h264_nvenc": broken},
    )
    job = new_id("job")
    with pytest.raises(RenderFailed) as caught:
        renderer.run(
            {"project_id": pid, "preset_id": "horizontal-720p30", "encoder": "h264_nvenc"},
            job_id=job,
        )
    assert caught.value.error.code == "render.hardware_encoder_failed"
    record = renderer.get(job)
    assert record["status"] == "failed"
    assert record["fallback"]["encoder"] == "libx264"
    assert record["plan"]["encoder"]["quality_note"] == "NVENC note."
    assert "output" not in record
    # Nothing switched silently: the CPU render is a separate, explicit choice.
    cpu = renderer.run(
        {"project_id": pid, "preset_id": "horizontal-720p30", "encoder": "libx264"},
        job_id=new_id("job"),
    )
    assert_ready(cpu, 2000)
    assert cpu["encoder"] == "libx264"


def test_unavailable_hardware_is_refused_before_rendering(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "x.mp4", "testsrc2", 1, tone=None)
    pid = studio.project(clip)
    status = {e["id"]: e for e in studio.renderer.encoder_status()["encoders"]}
    assert status["libx264"]["available"]
    missing = next((e for e in status.values() if not e["available"]), None)
    if missing is None:
        pytest.skip("every hardware encoder is available on this machine")
    with pytest.raises(RenderError) as caught:
        studio.renderer.check_request(
            {"project_id": pid, "preset_id": "horizontal-720p30", "encoder": missing["id"]}
        )
    assert caught.value.code == "render.encoder_unavailable"


def test_disk_full_is_refused_up_front(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "d.mp4", "testsrc2", 2, tone=440)
    pid = studio.project(clip)

    class Usage:
        free = 1024

    monkeypatch.setattr("openworld_moments.render.service.shutil.disk_usage", lambda _: Usage())
    job = new_id("job")
    with pytest.raises(RenderFailed) as caught:
        studio.renderer.run({"project_id": pid, "preset_id": "horizontal-720p30"}, job_id=job)
    assert caught.value.error.code == "render.disk_full"
    assert studio.renderer.get(job)["status"] == "failed"


def test_validation_catches_empty_truncated_and_black_output(
    studio: Studio, ffmpeg: ToolInfo, tools: MediaTools, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "v.mp4", "testsrc2", 3, tone=440)
    pid = studio.project(clip)
    record = studio.render(pid)
    plan, good = record["plan"], studio.output(record)
    cancel = threading.Event()
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert not validate_output(tools, empty, plan, [clip], cancel)["passed"]
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 3])
    result = validate_output(tools, truncated, plan, [clip], cancel)
    assert not result["passed"]
    wrong = copy.deepcopy(plan)
    wrong["duration_ms"] = plan["duration_ms"] + 500
    checks = {c["name"]: c for c in validate_output(tools, good, wrong, [clip], cancel)["checks"]}
    assert not checks["duration"]["passed"]
    # A black output where the source is bright is a filter error.
    black = make_clip(ffmpeg, tmp_path / "black.mp4", "color=c=black", 3, tone=None)
    silent = copy.deepcopy(plan)
    silent["output"]["audio"] = False
    silent["output"]["width"], silent["output"]["height"] = 640, 360
    checks = {c["name"]: c for c in validate_output(tools, black, silent, [clip], cancel)["checks"]}
    assert (
        not checks["black_frames"]["passed"]
        and "Black where the source is not" in checks["black_frames"]["detail"]
    )
    # Black source footage rendered black is fine.
    checks = {
        c["name"]: c for c in validate_output(tools, black, silent, [black], cancel)["checks"]
    }
    assert checks["black_frames"]["passed"]


def test_changed_sources_and_text_are_refused(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "c.mp4", "testsrc2", 2, tone=440)
    pid = studio.project(clip)
    studio.edit(
        pid,
        lambda p: p.update(
            overlays=[
                {
                    "kind": "text",
                    "start_ms": 0,
                    "end_ms": 500,
                    "region": [0, 0, 1, 0.1],
                    "text": "Hi",
                }
            ]
        ),
    )
    with pytest.raises(RenderError) as caught:
        studio.renderer.check_request({"project_id": pid, "preset_id": "horizontal-720p30"})
    assert caught.value.code == "render.text_unsupported"
    record = studio.render(pid, omit_text=True)
    assert record["plan"]["omitted"] == ["text_overlays"]
    # Same size, different bytes: the identity check catches it before rendering.
    data = bytearray(clip.read_bytes())
    data[-10] ^= 0xFF
    clip.write_bytes(bytes(data))
    job = new_id("job")
    with pytest.raises(RenderFailed) as failed:
        studio.renderer.run(
            {"project_id": pid, "preset_id": "horizontal-720p30", "omit_text": True}, job_id=job
        )
    assert failed.value.error.code == "render.source_changed"


def test_job_and_api_surface(studio: Studio, ffmpeg: ToolInfo, tmp_path: Path) -> None:
    clip = make_clip(ffmpeg, tmp_path / "api.mp4", "testsrc2", 2, tone=440)
    pid = studio.project(clip)
    settings = ApiSettings(
        secrets.token_hex(32), frozenset({"testserver"}), require_loopback_peer=False
    )
    derived = DerivedMedia(studio.database, studio.tools)
    engine = JobEngine(
        studio.database,
        build_handlers(
            studio.tools, database=studio.database, derived=derived, renderer=studio.renderer
        ),
    )
    with TestClient(
        create_app(engine, settings, derived=derived, renderer=studio.renderer)
    ) as client:
        assert client.get("/v1/render/presets").status_code == 401
        client.headers["Authorization"] = f"Bearer {settings.token}"
        presets = client.get("/v1/render/presets").json()
        assert {p["id"] for p in presets} == {
            "horizontal-1080p30",
            "horizontal-source-fps",
            "horizontal-720p30",
            "vertical-1080x1920-30",
            "vertical-source-fps",
        }
        encoders = client.get("/v1/render/encoders").json()
        assert next(e for e in encoders["encoders"] if e["id"] == "libx264")["available"]
        bad = client.post(f"/v1/projects/{pid}/render", json={"preset_id": "vertical-9000"})
        assert bad.status_code == 422 and "preset" in json.dumps(bad.json())
        response = client.post(
            f"/v1/projects/{pid}/render",
            json={"preset_id": "horizontal-720p30", "idempotency_key": "render-once"},
        )
        assert response.status_code == 201 and response.json()["kind"] == "render"
        job_id = response.json()["id"]
        wait_for(
            lambda: client.get(f"/v1/jobs/{job_id}").json()["state"] in ("ready", "failed"),
            timeout=120,
        )
        job = client.get(f"/v1/jobs/{job_id}").json()
        assert job["state"] == "ready", job
        assert job["result"]["status"] == "ready"
        assert client.get(f"/v1/renders/{job_id}").json()["output"]["duration_ms"] == 2000
        assert [r["id"] for r in client.get(f"/v1/projects/{pid}/renders").json()] == [job_id]
        assert client.get("/v1/renders/job_01JCBQ00000000000000000099").status_code == 404


def test_real_hardware_encoder_when_available(
    studio: Studio, ffmpeg: ToolInfo, tmp_path: Path
) -> None:
    """Renders with every hardware encoder that passes the probe on this machine."""
    available = [
        e["id"]
        for e in studio.renderer.encoder_status()["encoders"]
        if e["kind"] == "hardware" and e["available"]
    ]
    if not available:
        pytest.skip("no hardware H.264 encoder passes the probe on this machine")
    clip = make_clip(ffmpeg, tmp_path / "hw-real.mp4", "testsrc2", 3, tone=440)
    pid = studio.project(clip)
    for encoder in available:
        record = studio.render(pid, encoder=encoder)
        assert_ready(record, 3000)
        assert record["plan"]["encoder"]["kind"] == "hardware"
        assert record["plan"]["encoder"]["quality_note"]
