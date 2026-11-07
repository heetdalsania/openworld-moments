# SPDX-License-Identifier: AGPL-3.0-or-later
"""Overlap alignment against real FFmpeg fingerprints (M12): exact, recompressed,
audio-shifted, silent, repeated-scene, and no-overlap clip pairs; overrides,
version invalidation, cancellation, and untouched sources."""

from __future__ import annotations

import contextlib
import hashlib
import threading
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.alignment import overlap, service
from openworld_moments.alignment.service import AlignCancelled, Aligner
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.sessions.service import SessionError, SessionService
from openworld_moments.storage import (
    Database,
    Session,
    SessionAsset,
    SessionRepository,
    transaction,
    utc_now,
)

# 70 s of chaotic video (every frame differs) and quasi-periodic audio.
LIFE = "life=s=320x180:rate=30:ratio=0.3:seed={seed}:mold=10"
TONE = "aevalsrc='0.4*sin(2*PI*440*t)*(0.55+0.45*sin(2*PI*0.37*t)*sin(2*PI*1.13*t))':s=48000"


def _ffmpeg(ffmpeg: ToolInfo, *args: str) -> None:
    argv = [*ffmpeg.command, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args]
    result = run_tool(argv, timeout_s=300)
    assert result.returncode == 0, result.stderr_tail


X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "96k"]


@pytest.fixture(scope="session")
def clips(tmp_path_factory: pytest.TempPathFactory, ffmpeg: ToolInfo) -> Path:
    out = tmp_path_factory.mktemp("overlap-clips")
    master = out / "master.mkv"
    _ffmpeg(
        ffmpeg,
        *("-f", "lavfi", "-i", LIFE.format(seed=7)),
        *("-f", "lavfi", "-i", TONE),
        *("-t", "70", *X264, "-crf", "18", *AAC, str(master)),
    )

    def cut(name: str, start: float, length: float, *extra: str, audio: bool = True) -> None:
        tail = [*AAC] if audio else ["-an"]
        _ffmpeg(
            ffmpeg,
            *("-ss", f"{start}", "-t", f"{length}", "-i", str(master)),
            *X264,
            *extra,
            *tail,
            str(out / name),
        )

    cut("a.mp4", 0, 40)  # A: master 0-40 s
    cut("b.mp4", 30, 40)  # B: master 30-70 s, repeats A's last 10 s
    cut("b_recompressed.mp4", 30, 40, "-crf", "38", "-vf", "scale=256:144,scale=320:180")
    cut("a_silent.mp4", 0, 40, audio=False)
    cut("b_silent.mp4", 30, 40, audio=False)
    cut("c.mp4", 45, 25)  # no overlap with A (starts 5 s after A ends)
    # B with its audio 300 ms late relative to its picture.
    _ffmpeg(
        ffmpeg,
        *("-ss", "30", "-t", "40", "-i", str(master)),
        *("-af", "adelay=300|300", *X264, *AAC, str(out / "b_audio_late.mp4")),
    )
    # Repeated scene: A ends on a static menu, D starts on the same menu, then
    # unrelated footage.
    _ffmpeg(
        ffmpeg,
        *("-ss", "0", "-t", "30", "-i", str(master)),
        *("-f", "lavfi", "-i", "smptebars=s=320x180:r=30:d=8"),
        *("-f", "lavfi", "-i", f"{TONE}:d=8"),
        "-filter_complex",
        "[0:v][0:a][1:v][2:a]concat=n=2:v=1:a=1[v][a]",
        *("-map", "[v]", "-map", "[a]", *X264, *AAC, str(out / "a_menu.mp4")),
    )
    _ffmpeg(
        ffmpeg,
        *("-f", "lavfi", "-i", "smptebars=s=320x180:r=30:d=8"),
        *("-f", "lavfi", "-i", LIFE.format(seed=99) + ":rate=30"),
        *("-f", "lavfi", "-i", TONE),
        "-filter_complex",
        "[1:v]trim=duration=22,setpts=PTS-STARTPTS[life];[0:v][life]concat=n=2:v=1:a=0[v];"
        "[2:a]atrim=duration=30[a]",
        *("-map", "[v]", "-map", "[a]", *X264, *AAC, str(out / "d_menu.mp4")),
    )
    return out


class Library:
    def __init__(self, root: Path, tools: MediaTools) -> None:
        self.database = Database.open(root / "database.sqlite3")
        self.importer = Importer(self.database, tools)
        self.aligner = Aligner(self.database, self.importer.fingerprinter)
        self.sessions = SessionService(self.database)

    def add(self, path: Path) -> str:
        result = self.importer.run_import(
            {"paths": [str(path)], "mode": "reference", "recursive": False, "source_kind": "xbox"},
            job_id=new_id("job"),
            cancel=threading.Event(),
            progress=lambda *_: None,
            set_state=lambda _: None,
        )
        asset_id: str = result["items"][0]["asset_id"]
        return asset_id

    def session(self, *asset_ids: str) -> str:
        sid = new_id("ses")
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            repo = SessionRepository(conn)
            repo.add(Session(id=sid, title="Test", created_at=utc_now()))
            for i, asset_id in enumerate(asset_ids):
                repo.add_asset(
                    SessionAsset(
                        session_id=sid, asset_id=asset_id, order_index=i, session_start_ms=i
                    )
                )
        return sid

    def align(self, **params: Any) -> dict[str, Any]:
        return self.aligner.run(params)

    def overlaps(self, sid: str) -> list[dict[str, Any]]:
        with contextlib.closing(self.database.connect()) as conn:
            docs = self.aligner.overlaps_doc(conn, sid)
        for doc in docs:
            load("overlap", doc)
        return docs

    def doc(self, sid: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            doc = self.sessions.doc(conn, sid)
        load("session", doc)
        return doc


@pytest.fixture
def library(tmp_path: Path, ffmpeg: ToolInfo, ffprobe: ToolInfo) -> Library:
    return Library(tmp_path / "library", MediaTools())


TRUE_OFFSET_MS = 30_000


def _pair(library: Library, clips: Path, a: str, b: str) -> tuple[str, dict[str, Any]]:
    sid = library.session(library.add(clips / a), library.add(clips / b))
    library.align()
    (doc,) = library.overlaps(sid)
    return sid, doc


@pytest.mark.parametrize(
    "b_name",
    ["b.mp4", "b_recompressed.mp4", "b_audio_late.mp4"],
    ids=["exact", "recompressed", "audio-shifted"],
)
def test_known_overlaps_align_within_500ms(library: Library, clips: Path, b_name: str) -> None:
    before = hashlib.sha256((clips / "a.mp4").read_bytes()).hexdigest()
    sid, doc = _pair(library, clips, "a.mp4", b_name)
    assert doc["status"] == "matched", doc
    assert abs(doc["offset_ms"] - TRUE_OFFSET_MS) <= 500, doc
    assert abs(doc["overlap_ms"] - 10_000) <= 500
    assert doc["applied"]["source"] == "auto"
    session = library.doc(sid)
    second = session["assets"][1]
    assert abs(second["overlap_with_previous_ms"] - 10_000) <= 500
    assert abs(second["session_start_ms"] - TRUE_OFFSET_MS) <= 500  # B starts 30 s into A
    assert hashlib.sha256((clips / "a.mp4").read_bytes()).hexdigest() == before


def test_audio_refines_an_exact_overlap(library: Library, clips: Path) -> None:
    _, doc = _pair(library, clips, "a.mp4", "b.mp4")
    assert doc["evidence"].get("audio_correlation", 0) >= overlap.AUDIO_MIN_CORRELATION
    assert abs(doc["offset_ms"] - TRUE_OFFSET_MS) <= 150


def test_silent_clips_align_visually(library: Library, clips: Path) -> None:
    _, doc = _pair(library, clips, "a_silent.mp4", "b_silent.mp4")
    assert doc["status"] == "matched"
    assert abs(doc["offset_ms"] - TRUE_OFFSET_MS) <= 500
    assert "audio_correlation" not in doc["evidence"]


def test_no_overlap_leaves_both_clips_whole(library: Library, clips: Path) -> None:
    sid, doc = _pair(library, clips, "a.mp4", "c.mp4")
    assert doc["status"] == "no_match" and doc["applied"] == {"overlap_ms": 0, "source": "none"}
    assert "overlap_with_previous_ms" not in library.doc(sid)["assets"][1]


def test_repeated_menu_is_not_a_confident_overlap(library: Library, clips: Path) -> None:
    sid, doc = _pair(library, clips, "a_menu.mp4", "d_menu.mp4")
    assert doc["status"] in ("ambiguous", "no_match", "weak"), doc
    assert doc["applied"]["source"] == "none"
    assert "overlap_with_previous_ms" not in library.doc(sid)["assets"][1]


def test_override_wins_over_recomputation(library: Library, clips: Path) -> None:
    sid, doc = _pair(library, clips, "a.mp4", "b.mp4")
    b = doc["asset_b"]
    updated = library.aligner.set_override(sid, b, 0)  # "these do not overlap"
    assert "overlap_with_previous_ms" not in updated["assets"][1]
    result = library.align(force=True)
    assert result["computed"] == 1
    (again,) = library.overlaps(sid)
    assert again["status"] == "matched" and again["override"]["overlap_ms"] == 0
    assert again["applied"] == {"overlap_ms": 0, "source": "user", "confidence": 1}
    library.aligner.set_override(sid, b, 4000)
    assert library.doc(sid)["assets"][1]["overlap_with_previous_ms"] == 4000
    library.aligner.set_override(sid, b, None)  # back to the automatic result
    assert abs(library.doc(sid)["assets"][1]["overlap_with_previous_ms"] - 10_000) <= 500
    with pytest.raises(SessionError):
        library.aligner.set_override(sid, doc["asset_a"], 1000)  # the first clip
    with pytest.raises(SessionError):
        library.aligner.set_override(sid, b, 10**9)  # longer than the clips


def test_results_are_cached_and_invalidated_by_version(
    library: Library, clips: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid, _ = _pair(library, clips, "a.mp4", "b.mp4")
    again = library.align()
    assert again["cached"] == 1 and again["computed"] == 0 and again["sessions_updated"] == 0
    monkeypatch.setattr(service, "ALIGN_VERSION", overlap.ALIGN_VERSION + 1)
    monkeypatch.setattr(
        "openworld_moments.sessions.service.ALIGN_VERSION", overlap.ALIGN_VERSION + 1
    )
    stale = library.overlaps(sid)[0]
    assert stale["current"] is False and stale["applied"]["source"] == "none"
    recomputed = library.align()
    assert recomputed["computed"] == 1 and recomputed["cached"] == 0
    fresh = library.overlaps(sid)[0]
    assert fresh["version"] == overlap.ALIGN_VERSION + 1 and fresh["current"] is True


def test_cancelling_stops_between_pairs(library: Library, clips: Path) -> None:
    ids = [library.add(clips / n) for n in ("a.mp4", "b.mp4", "c.mp4")]
    library.session(*ids)
    cancel = threading.Event()
    seen: list[int] = []

    def progress(done: int, total: int, _: str) -> None:
        seen.append(done)
        if done >= 1:
            cancel.set()

    with pytest.raises(AlignCancelled):
        library.aligner.run({}, cancel=cancel, progress=progress)
    result = library.align()  # the first pair was saved; the rest resumes
    assert result["cached"] == 1 and result["computed"] == 1


def test_regrouping_keeps_applied_overlaps(library: Library, clips: Path) -> None:
    a, b = library.add(clips / "a.mp4"), library.add(clips / "b.mp4")
    library.sessions.recompute({"max_gap_ms": 86_400_000})
    with contextlib.closing(library.database.connect()) as conn:
        (session,) = library.sessions.list_docs(conn, limit=10, offset=0)
    library.align()
    aligned = library.doc(session["id"])
    assert [m["asset_id"] for m in aligned["assets"]] == [a, b]
    assert aligned["assets"][1].get("overlap_with_previous_ms", 0) > 9_000
    result = library.sessions.recompute({"max_gap_ms": 86_400_000})
    assert result["sessions_unchanged"] == 1  # the overlap is part of the stable layout
    assert library.doc(session["id"])["assets"][1]["overlap_with_previous_ms"] > 9_000
