# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fingerprints and duplicate candidates (M06).

Required validation: exact, renamed, remux, recompressed, and near-match cases;
a memory smoke test on a large sparse file; a backfill restart test.
"""

from __future__ import annotations

import shutil
import threading
import tracemalloc
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.fingerprints import algorithms as alg
from openworld_moments.fingerprints.service import (
    FingerprintCancelled,
    Fingerprinter,
    FingerprintFailure,
    fingerprints_doc,
)
from openworld_moments.ingest import files as files_module
from openworld_moments.ingest.files import ImportCancelled, hash_file
from openworld_moments.ingest.importer import ImportFailure
from openworld_moments.media.process import run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo
from openworld_moments.storage import (
    DuplicateCandidateRepository,
    FingerprintRepository,
    transaction,
)
from tests.media.test_import import Harness

CLIP_S = 8


def _ffmpeg_run(ffmpeg: ToolInfo, *args: str) -> None:
    result = run_tool(
        [*ffmpeg.command, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        timeout_s=120,
    )
    assert result.returncode == 0, result.stderr_tail


@pytest.fixture(scope="session")
def clips(tmp_path_factory: pytest.TempPathFactory, ffmpeg: ToolInfo) -> Path:
    """8-second synthetic clips: an original, its remux and re-encode, and look-alikes."""
    out = tmp_path_factory.mktemp("fingerprint-clips")
    src = f"testsrc2=size=320x180:rate=30:duration={CLIP_S}"
    # Beeps, not a steady tone: a constant loudness has no defined correlation.
    tone = f"sine=frequency=440:beep_factor=4:duration={CLIP_S}"
    x264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    _ffmpeg_run(
        ffmpeg,
        "-f",
        "lavfi",
        "-i",
        src,
        "-f",
        "lavfi",
        "-i",
        tone,
        *x264,
        "-c:a",
        "aac",
        "-shortest",
        str(out / "base.mp4"),
    )
    _ffmpeg_run(ffmpeg, "-i", str(out / "base.mp4"), "-c", "copy", str(out / "remux.mkv"))
    _ffmpeg_run(
        ffmpeg,
        "-i",
        str(out / "base.mp4"),
        "-vf",
        "scale=640:360",
        *x264,
        "-crf",
        "35",
        "-c:a",
        "aac",
        str(out / "recompressed.mp4"),
    )
    for seed in (1, 2):  # same texture, different content
        _ffmpeg_run(
            ffmpeg,
            "-f",
            "lavfi",
            "-i",
            f"life=s=320x180:seed={seed}:ratio=0.3:rate=30",
            "-t",
            str(CLIP_S),
            *x264,
            str(out / f"life{seed}.mp4"),
        )
    # The same mostly static test pattern, ten seconds later: similar, not the same.
    _ffmpeg_run(
        ffmpeg,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=30:duration=20",
        "-vf",
        "trim=start=10,setpts=PTS-STARTPTS",
        "-t",
        str(CLIP_S),
        *x264,
        str(out / "later.mp4"),
    )
    return out


@pytest.fixture
def harness(tmp_path: Path, ffprobe: ToolInfo) -> Iterator[Harness]:
    with closing(Harness(tmp_path, ffprobe)) as h:
        yield h


def _copy(clips: Path, name: str, dest: Path, new_name: str | None = None) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / (new_name or name)
    shutil.copyfile(clips / name, target)
    return target


def _item(result: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = result["items"][0]
    return item


# -- pure algorithms ------------------------------------------------------------------


def test_dhash_bits_and_flat_frames() -> None:
    row = bytes(range(200, 200 - 17 * 10, -10))  # every pixel brighter than its right neighbour
    value, flat = alg.dhash(row * 16)
    assert value == "f" * 64 and not flat
    assert alg.dhash(bytes([128]) * 272) == ("0" * 64, True)
    nearly_flat = bytes([100 + (i % 5) for i in range(272)])
    assert alg.dhash(nearly_flat)[1] is True
    with pytest.raises(ValueError, match="17x16"):
        alg.dhash(b"\0" * 72)


def _frames(hashes: list[str], *, flat: frozenset[int] = frozenset()) -> dict[str, Any]:
    head = [
        {"t_ms": i * 500, "hash": h, **({"flat": True} if i in flat else {})}
        for i, h in enumerate(hashes)
    ]
    return {"head": head, "tail": []}


def _with_bits(n: int) -> str:
    return f"{(1 << n) - 1:064x}"


def test_compare_frames_thresholds() -> None:
    zero = "0" * 64
    base = _frames([zero] * 5)
    exact = alg.compare_frames(base, _frames([zero] * 5), 8000, 8000)
    assert exact is not None and exact.score == 1.0
    at_limit = alg.compare_frames(
        base, _frames([_with_bits(alg.MATCH_MAX_DISTANCE)] * 5), 8000, 8000
    )
    assert at_limit is not None and at_limit.score == 0.5  # limit distance still matches
    over = alg.compare_frames(
        base, _frames([_with_bits(alg.MATCH_MAX_DISTANCE + 1)] * 5), 8000, 8000
    )
    assert over is None
    assert alg.compare_frames(base, _frames([zero] * 5), 8000, 12000) is None  # durations
    # Flat frames carry no identity: with three of five flat, too few frames remain.
    assert (
        alg.compare_frames(
            _frames([zero] * 5, flat=frozenset({0, 1, 2})), _frames([zero] * 5), 8000, 8000
        )
        is None
    )
    # Four of five matching (80%) qualifies; three of five does not.
    far = _with_bits(100)
    assert alg.compare_frames(base, _frames([zero] * 4 + [far]), 8000, 8000) is not None
    assert alg.compare_frames(base, _frames([zero] * 3 + [far] * 2), 8000, 8000) is None


def test_envelope_levels() -> None:
    assert alg.envelope([0] * 800) == [0]
    assert alg.envelope([32767, -32767] * 400) == [255]
    half = alg.envelope([16384, -16384] * 400)[0]
    assert 241 <= half <= 243  # -6 dBFS: (127.5 - 6) * 2 = 243
    assert alg.envelope([1] * 799) == []  # incomplete block dropped


def test_correlation() -> None:
    assert alg.correlation([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert alg.correlation([1, 2, 3, 4], [8, 6, 4, 2]) == -1.0
    assert alg.correlation([5, 5, 5], [1, 2, 3]) is None
    assert alg.correlation([1, 2], [1, 2]) is None


def test_windows() -> None:
    assert alg.windows(8000) == (alg.Window(0, 8000), alg.Window(0, 8000))
    assert alg.windows(90_000) == (alg.Window(0, 30_000), alg.Window(60_000, 30_000))


def test_fast_hash_collision_is_resolved_by_sha256(tmp_path: Path) -> None:
    span = alg.FAST_SPAN
    a = bytes(span) + b"A" * 4096 + bytes(span)
    b = bytes(span) + b"B" * 4096 + bytes(span)
    pa, pb = tmp_path / "a.bin", tmp_path / "b.bin"
    pa.write_bytes(a)
    pb.write_bytes(b)
    assert alg.fast_hash(pa, len(a)) == alg.fast_hash(pb, len(b))  # by construction
    stat_a, stat_b = pa.stat(), pb.stat()
    cancel = threading.Event()
    assert (
        hash_file(pa, cancel=cancel, expected=stat_a).sha256
        != hash_file(pb, cancel=cancel, expected=stat_b).sha256
    )
    assert alg.fast_hash(pa, len(a)) != alg.fast_hash(pa, len(a) + 1)  # size is part of it


# -- large files: memory, progress, cancellation --------------------------------------


@pytest.fixture
def sparse(tmp_path: Path) -> Path:
    path = tmp_path / "large.bin"
    with path.open("wb") as handle:
        handle.truncate(256 * 1024 * 1024)  # sparse where the filesystem supports it
    return path


def test_hashing_a_large_file_uses_bounded_memory(sparse: Path) -> None:
    info = sparse.stat()
    tracemalloc.start()
    try:
        hash_file(sparse, cancel=threading.Event(), expected=info)
        alg.fast_hash(sparse, info.st_size)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"peak {peak} bytes"


def test_hashing_reports_progress_and_can_be_cancelled(sparse: Path) -> None:
    info = sparse.stat()
    seen: list[int] = []
    hash_file(sparse, cancel=threading.Event(), expected=info, on_bytes=seen.append)
    assert seen[-1] == info.st_size and seen == sorted(seen) and len(seen) > 100

    cancel = threading.Event()

    def stop_halfway(read: int) -> None:
        if read >= info.st_size // 2:
            cancel.set()

    with pytest.raises(ImportCancelled):
        hash_file(sparse, cancel=cancel, expected=info, on_bytes=stop_halfway)


# -- import integration ---------------------------------------------------------------


def test_exact_and_renamed_duplicates_resolve_to_one_asset(
    clips: Path, harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _item(harness.run(_copy(clips, "base.mp4", tmp_path / "in"), mode="managed"))
    renamed = _copy(clips, "base.mp4", tmp_path / "elsewhere", "Renamed copy.mp4")

    def no_copy(*_: Any, **__: Any) -> None:
        raise AssertionError("a known file must not be copied to staging again")

    monkeypatch.setattr("openworld_moments.ingest.importer.stage_copy", no_copy)
    again = _item(harness.run(renamed, mode="managed"))
    assert again["outcome"] == "existing" and again["asset_id"] == first["asset_id"]
    assert harness.asset_count() == 1
    asset = harness.assets().get(first["asset_id"])
    assert asset.fast_hash == alg.fast_hash(renamed, renamed.stat().st_size)


@pytest.mark.parametrize("variant", ["remux.mkv", "recompressed.mp4"])
def test_same_content_becomes_a_candidate_not_a_duplicate(
    clips: Path, harness: Harness, tmp_path: Path, variant: str
) -> None:
    base = _item(harness.run(_copy(clips, "base.mp4", tmp_path / "in"), mode="managed"))
    other = _item(harness.run(_copy(clips, variant, tmp_path / "in"), mode="managed"))
    assert other["outcome"] == "imported" and other["asset_id"] != base["asset_id"]
    assert other["candidate_asset_ids"] == [base["asset_id"]]
    assert harness.asset_count() == 2  # nothing collapsed
    assert len(list(harness.library.managed.rglob("*.*"))) == 2  # nothing deleted

    (candidate,) = DuplicateCandidateRepository(harness.assets().conn).query()
    assert candidate.review_state == "unreviewed"
    assert {candidate.asset_a, candidate.asset_b} == {base["asset_id"], other["asset_id"]}
    assert candidate.algorithm == alg.MATCH_ALGORITHM and candidate.version == alg.MATCH_VERSION
    assert candidate.evidence["matching_frames"] >= alg.MATCH_MIN_FRAMES
    assert "audio_correlation" in candidate.evidence  # both have the same tone
    if variant == "remux.mkv":
        # Every sampled frame matches. The score is 1.0 when both files sample the same
        # frames; some FFmpeg versions pick frames one frame-time apart in the remux
        # (about 0.83 seen with FFmpeg 8): still near-identical, still a candidate.
        evidence = candidate.evidence
        assert evidence["matching_frames"] == evidence["compared_frames"]
        assert candidate.score >= 0.75


@pytest.mark.parametrize(
    ("first", "second"),
    [("life1.mp4", "life2.mp4"), ("base.mp4", "later.mp4"), ("base.mp4", "life1.mp4")],
)
def test_similar_but_distinct_clips_stay_separate(
    clips: Path, harness: Harness, tmp_path: Path, first: str, second: str
) -> None:
    harness.run(_copy(clips, first, tmp_path / "in"))
    result = _item(harness.run(_copy(clips, second, tmp_path / "in")))
    assert result["outcome"] == "imported"
    assert "candidate_asset_ids" not in result
    assert DuplicateCandidateRepository(harness.assets().conn).query() == []


def test_fingerprints_are_versioned_and_contract_valid(
    clips: Path, harness: Harness, tmp_path: Path
) -> None:
    with_audio = _item(harness.run(_copy(clips, "base.mp4", tmp_path / "in")))["asset_id"]
    silent = _item(harness.run(_copy(clips, "life1.mp4", tmp_path / "in")))["asset_id"]
    conn = harness.assets().conn
    doc = fingerprints_doc(conn, with_audio)
    load("fingerprint", doc)
    assert doc["fast_hash"]["algorithm"] == "owm-fast" and doc["fast_hash"]["version"] == 1
    frames = doc["frames"]
    assert (frames["algorithm"], frames["version"]) == ("dhash256", 1)
    assert len(frames["head"]) == CLIP_S * alg.SAMPLE_FPS
    assert frames["head"][1]["t_ms"] == 1000 // alg.SAMPLE_FPS
    audio = doc["audio"]
    expected = CLIP_S * alg.ENVELOPE_RATE_HZ  # AAC trims a few ms at the edges
    assert expected - 2 <= len(audio["head"]) <= expected
    assert max(audio["head"]) > 200  # a full-scale-ish tone, not silence
    assert "audio" not in fingerprints_doc(conn, silent)


# -- backfill -------------------------------------------------------------------------


def _strip_fingerprints(harness: Harness) -> None:
    conn = harness.assets().conn
    with transaction(conn):
        conn.execute("DELETE FROM asset_fingerprints WHERE kind <> 'fast'")
        conn.execute("DELETE FROM duplicate_candidates")


def _backfill(
    harness: Harness, cancel: threading.Event | None = None, **params: Any
) -> dict[str, Any]:
    fp = Fingerprinter(harness.database, MediaTools())
    return fp.backfill(params, cancel=cancel or threading.Event(), progress=lambda *_: None)


def test_backfill_restarts_where_it_stopped(clips: Path, harness: Harness, tmp_path: Path) -> None:
    for name in ("base.mp4", "remux.mkv", "life1.mp4"):
        harness.run(_copy(clips, name, tmp_path / "in"))
    _strip_fingerprints(harness)

    cancel = threading.Event()
    fp = Fingerprinter(harness.database, MediaTools())
    with pytest.raises(FingerprintCancelled):
        fp.backfill(
            {}, cancel=cancel, progress=lambda done, *_: cancel.set() if done == 1 else None
        )

    result = _backfill(harness)
    assert result == {
        "considered": 3,
        "updated": 2,
        "up_to_date": 1,
        "unavailable": 0,
        "failed": 0,
        "new_candidates": 1,
    }
    again = _backfill(harness)
    assert (again["updated"], again["up_to_date"]) == (0, 3)


def test_stale_version_is_recomputed(clips: Path, harness: Harness, tmp_path: Path) -> None:
    asset_id = _item(harness.run(_copy(clips, "base.mp4", tmp_path / "in")))["asset_id"]
    conn = harness.assets().conn
    with transaction(conn):  # as if written by an older algorithm
        conn.execute("UPDATE asset_fingerprints SET algorithm = 'dhash64' WHERE kind = 'frames'")
    assert _backfill(harness)["updated"] == 1
    stored = FingerprintRepository(conn).for_asset(asset_id)["frames"]
    assert (stored.algorithm, stored.version) == ("dhash256", 1)


def test_review_decision_survives_recomputation(
    clips: Path, harness: Harness, tmp_path: Path
) -> None:
    harness.run(_copy(clips, "base.mp4", tmp_path / "in"))
    harness.run(_copy(clips, "remux.mkv", tmp_path / "in"))
    repo = DuplicateCandidateRepository(harness.assets().conn)
    (candidate,) = repo.query()
    with transaction(repo.conn):
        repo.set_review_state(candidate.id, "distinct")
    result = _backfill(harness, force=True)
    assert result["new_candidates"] == 0
    (after,) = repo.query()
    assert after.id == candidate.id and after.review_state == "distinct"
    assert harness.asset_count() == 2


def test_backfill_counts_unavailable_sources(clips: Path, harness: Harness, tmp_path: Path) -> None:
    source = _copy(clips, "life1.mp4", tmp_path / "in")
    harness.run(source)
    _strip_fingerprints(harness)
    source.unlink()
    assert _backfill(harness)["unavailable"] == 1


def test_missing_ffmpeg(
    clips: Path, harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = ToolInfo("ffmpeg", (), "path", "missing", None, problem="not found")
    real = MediaTools.tool
    monkeypatch.setattr(
        MediaTools, "tool", lambda self, name: missing if name == "ffmpeg" else real(self, name)
    )
    # The import still succeeds (fast hash only); perceptual fingerprints wait for backfill.
    asset_id = _item(harness.run(_copy(clips, "base.mp4", tmp_path / "in")))["asset_id"]
    stored = FingerprintRepository(harness.assets().conn).for_asset(asset_id)
    assert set(stored) == {"fast"}
    with pytest.raises(FingerprintFailure) as caught:
        _backfill(harness)
    assert caught.value.code == "tool.ffmpeg_missing" and caught.value.retryable


def test_undecodable_sample_is_reported_not_fatal(
    clips: Path, harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.run(_copy(clips, "life1.mp4", tmp_path / "in"))
    _strip_fingerprints(harness)

    def broken(*_: Any, **__: Any) -> list[dict[str, Any]]:
        raise alg.DecodeError("fingerprint.decode_failed", "cannot decode")

    monkeypatch.setattr(alg, "frame_hashes", broken)
    assert _backfill(harness)["failed"] == 1


def test_chunk_size_is_bounded() -> None:
    assert files_module.CHUNK_BYTES <= 4 * 1024 * 1024


# -- API ------------------------------------------------------------------------------


def test_fingerprint_and_duplicate_endpoints(
    clips: Path, tmp_path: Path, ffprobe: ToolInfo
) -> None:
    from tests.media.test_import_api import _finished, _make_client

    folder = tmp_path / "captures"
    _copy(clips, "base.mp4", folder)
    _copy(clips, "remux.mkv", folder)
    with _make_client(tmp_path / "library", ffprobe) as api:
        job = _finished(
            api,
            api.post("/v1/imports", json={"paths": [str(folder)], "mode": "reference"}).json()[
                "id"
            ],
        )
        assert job["state"] == "ready", job
        items = {i["relative_path"]: i for i in job["result"]["items"]}
        base_id = items["base.mp4"]["asset_id"]
        remux_id = items["remux.mkv"]["asset_id"]
        assert items["remux.mkv"]["candidate_asset_ids"] == [base_id]

        prints = api.get(f"/v1/assets/{base_id}/fingerprints")
        assert prints.status_code == 200
        load("fingerprint", prints.json())

        (candidate,) = api.get("/v1/duplicates").json()
        assert candidate["asset_ids"] == sorted([base_id, remux_id])
        assert candidate["review_state"] == "unreviewed"
        assert api.get(f"/v1/duplicates/{candidate['id']}").json() == candidate
        assert api.get("/v1/duplicates", params={"asset_id": remux_id}).json() == [candidate]

        reviewed = api.patch(f"/v1/duplicates/{candidate['id']}", json={"review_state": "distinct"})
        assert reviewed.status_code == 200 and reviewed.json()["review_state"] == "distinct"
        assert api.get("/v1/duplicates", params={"review_state": "unreviewed"}).json() == []
        assert (
            api.patch(
                f"/v1/duplicates/{candidate['id']}", json={"review_state": "delete"}
            ).status_code
            == 422
        )

        backfill = api.post("/v1/fingerprints/backfill", json={"force": True})
        assert backfill.status_code == 201
        done = _finished(api, backfill.json()["id"])
        assert done["kind"] == "fingerprint" and done["state"] == "ready", done
        assert done["result"]["updated"] == 2 and done["result"]["new_candidates"] == 0
        assert api.get(f"/v1/duplicates/{candidate['id']}").json()["review_state"] == "distinct"
        assert len(api.get("/v1/assets").json()) == 2  # nothing merged or deleted

        assert api.get("/v1/assets/ast_01JCBQ00000000000000000000/fingerprints").status_code == 404
        assert api.get("/v1/duplicates/999").status_code == 404
        bad = api.post("/v1/fingerprints/backfill", json={"asset_ids": ["nope"]})
        assert bad.status_code == 422 and "'asset_ids'" in bad.json()["message"]


def test_relink_rejects_a_different_file_after_the_fast_hash(
    clips: Path, harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _copy(clips, "base.mp4", tmp_path / "in")
    asset_id = _item(harness.run(source))["asset_id"]
    tampered = tmp_path / "tampered.mp4"
    data = bytearray(source.read_bytes())
    data[0] ^= 0xFF  # inside the first MiB: the fast hash differs
    tampered.write_bytes(bytes(data))

    def no_full_read(*_: Any, **__: Any) -> None:
        raise AssertionError("the fast hash should reject this file without a full read")

    monkeypatch.setattr("openworld_moments.ingest.importer.hash_file", no_full_read)
    with pytest.raises(ImportFailure) as caught:
        harness.importer.relink(
            {"asset_id": asset_id, "path": str(tampered)},
            job_id="job_01JCBQ00000000000000000077",
            cancel=threading.Event(),
        )
    assert caught.value.code == "relink.identity_mismatch"
