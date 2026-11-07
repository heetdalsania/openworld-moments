# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audio features through the real path (M18): generated clips → import → M08 proxy
(AAC) → FFmpeg analysis audio → the built-in detector → persisted events. Covers time
alignment after re-encoding, silence, no-audio and multi-track clips, cancellation,
cache reuse and source preservation. All media is generated."""

from __future__ import annotations

import contextlib
import hashlib
import threading
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.derived.service import DerivedMedia
from openworld_moments.detectors.audio_input import decode_audio
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.detectors.service import Analyzer
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.media.process import ToolCancelled, run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database, DerivedArtifactRepository, EventRepository

#: AAC re-encoding plus 10 ms hops: measured within ±10 ms; asserted with margin.
IMPACT_TOLERANCE_MS = 30
BOUNDARY_TOLERANCE_MS = 150

SPEECH = (
    "if(between(t,1,4),0.25*pow(max(0,sin(2*PI*4*t)),2)*(sin(2*PI*280*t)+0.5*sin(2*PI*420*t)"
    "+0.33*sin(2*PI*560*t)+0.25*sin(2*PI*840*t)+0.2*sin(2*PI*1120*t)+0.1*sin(2*PI*2240*t)),0)"
)
IMPACT = "if(between(t,5.25,5.33),0.6*exp(-(t-5.25)/0.015)*sin(2*PI*1500*t),0)"
FLOOR = "0.002*sin(2*PI*997*t)"


def make_clip(ffmpeg: ToolInfo, target: Path, audio: list[str] | None, seconds: int = 8) -> Path:
    args = ["-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=30:duration={seconds}"]
    maps = ["-map", "0:v"]
    for index, expression in enumerate(audio or [], start=1):
        args += ["-f", "lavfi", "-i", f"aevalsrc='{expression}':s=48000:d={seconds}"]
        maps += ["-map", f"{index}:a"]
    codec = ["-c:a", "aac", "-b:a", "128k"] if audio else ["-an"]
    result = run_tool(
        [
            *ffmpeg.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            *args,
            *maps,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            *codec,
            str(target),
        ],
        timeout_s=120,
    )
    assert result.returncode == 0, result.stderr_tail
    return target


class Library:
    def __init__(self, root: Path, tools: MediaTools) -> None:
        self.database = Database.open(root / "library" / "database.sqlite3")
        self.tools = tools
        self.derived = DerivedMedia(self.database, tools)
        self.analyzer = Analyzer(self.database, tools, self.derived)

    def session_for(self, *clips: Path) -> str:
        Importer(self.database, self.tools).run_import(
            {"paths": [str(c) for c in clips], "mode": "reference", "recursive": False},
            job_id=new_id("job"),
            cancel=threading.Event(),
            progress=lambda *_: None,
        )
        SessionService(self.database).recompute({})
        with contextlib.closing(self.database.connect()) as conn:
            docs = SessionService(self.database).list_docs(conn, limit=10, offset=0)
        assert len(docs) == 1
        return str(docs[0]["id"])

    def analyze(self, sid: str, **extra: Any) -> dict[str, Any]:
        return self.analyzer.run(
            {"session_id": sid, "profile_id": "generic-audio", **extra}, job_id=new_id("job")
        )

    def events(self, sid: str) -> list[Any]:
        with contextlib.closing(self.database.connect()) as conn:
            return EventRepository(conn).list_for_session(sid)


@pytest.fixture
def library(tmp_path: Path, tools: MediaTools) -> Library:
    return Library(tmp_path, tools)


def test_features_survive_the_proxy_and_stay_time_aligned(
    tmp_path: Path, library: Library, ffmpeg: ToolInfo
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "mixed.mp4", [f"{FLOOR}+{SPEECH}+{IMPACT}"])
    before = hashlib.sha256(clip.read_bytes()).hexdigest(), clip.stat().st_mtime_ns
    sid = library.session_for(clip)
    result = library.analyze(sid)
    assert [o["status"] for o in result["outcomes"]] == ["computed"]
    events = library.events(sid)
    by_type: dict[str, list[Any]] = {}
    for event in events:
        by_type.setdefault(event.type, []).append(event)
    impacts = by_type["openworld.audio_impact"]
    assert len(impacts) == 1
    assert abs(impacts[0].start_ms - 5250) <= IMPACT_TOLERANCE_MS
    speech = by_type["openworld.speech_activity"]
    assert len(speech) == 1
    assert abs(speech[0].start_ms - 1000) <= BOUNDARY_TOLERANCE_MS
    assert abs(speech[0].end_ms - 4000) <= BOUNDARY_TOLERANCE_MS
    # Quiet floor before the speech, between speech and impact, and after the impact.
    silences = [(e.start_ms, e.end_ms) for e in by_type["openworld.silence"]]
    expected = [(0, 1000), (4000, 5250), (5330, 8000)]
    assert len(silences) == len(expected), silences
    for (start, end), (want_start, want_end) in zip(silences, expected, strict=True):
        assert abs(start - want_start) <= BOUNDARY_TOLERANCE_MS, silences
        assert abs(end - want_end) <= BOUNDARY_TOLERANCE_MS, silences
    for event in events:
        assert event.attributes["evidence_role"] == "supporting"
        assert event.source.tool_versions is not None
        versions = event.source.tool_versions
        assert versions["sampler"] == "pcm8k-mono-speechband-v1"
        assert versions["audio_track"] == "first-of-1"
        assert versions["sdk"] == "1.3.0"
    # A rerun is served from the cache; sources are never modified.
    assert library.analyze(sid)["outcomes"][0]["status"] == "cached"
    assert (hashlib.sha256(clip.read_bytes()).hexdigest(), clip.stat().st_mtime_ns) == before


def test_silent_clip_completes_with_silence_only(
    tmp_path: Path, library: Library, ffmpeg: ToolInfo
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "silent.mp4", ["0"], seconds=4)
    sid = library.session_for(clip)
    assert library.analyze(sid)["outcomes"][0]["status"] == "computed"
    events = library.events(sid)
    assert [e.type for e in events] == ["openworld.silence"]
    assert events[0].start_ms == 0 and events[0].end_ms >= 3800


def test_clip_without_audio_completes_without_events(
    tmp_path: Path, library: Library, ffmpeg: ToolInfo
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "no audio.mp4", None, seconds=3)
    sid = library.session_for(clip)
    outcome = library.analyze(sid)["outcomes"][0]
    assert outcome["status"] == "computed" and outcome["event_ids"] == []
    assert library.events(sid) == []


def test_multi_track_clip_analyzes_the_first_stream(
    tmp_path: Path, library: Library, ffmpeg: ToolInfo
) -> None:
    # Stream 0 is silent, stream 1 has an impact: policy = first stream only.
    clip = make_clip(ffmpeg, tmp_path / "two tracks.mp4", ["0", f"{FLOOR}+{IMPACT}"])
    sid = library.session_for(clip)
    assert library.analyze(sid)["outcomes"][0]["status"] == "computed"
    events = library.events(sid)
    assert {e.type for e in events} == {"openworld.silence"}
    assert events[0].source.tool_versions["audio_track"] == "first-of-2"


def test_decode_cancellation_kills_ffmpeg(
    tmp_path: Path, library: Library, ffmpeg: ToolInfo
) -> None:
    clip = make_clip(ffmpeg, tmp_path / "cancel.mp4", [FLOOR], seconds=3)
    sid = library.session_for(clip)
    library.analyze(sid)  # creates the proxy
    with contextlib.closing(library.database.connect()) as conn:
        links = conn.execute("SELECT asset_id FROM session_assets").fetchall()
        row = DerivedArtifactRepository(conn).get(links[0][0], "proxy")
    assert row is not None and row.relpath is not None
    proxy = library.derived.paths.resolve(row.relpath)
    assert proxy is not None
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ToolCancelled):
        decode_audio(proxy, ffmpeg, cancel)
    with pytest.raises(AnalysisCancelled):
        library.analyzer.run(
            {"session_id": sid, "profile_id": "generic-audio", "force": True},
            job_id=new_id("job"),
            cancel=cancel,
        )
