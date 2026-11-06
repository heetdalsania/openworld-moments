# SPDX-License-Identifier: AGPL-3.0-or-later
"""Derived media against real FFmpeg and synthetic fixtures (M08): SDR, HDR, silent,
rotated, and VFR clips; determinism, cache hits and invalidation, missing-file
rebuilds, cancellation, write failures, sampled-decode validation, and the API."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import secrets
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load

from openworld_moments.api.app import ApiSettings, create_app
from openworld_moments.derived import recipes, service, waveform
from openworld_moments.derived.service import DerivedCancelled, DerivedFailure, DerivedMedia
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.jobs.engine import JobEngine
from openworld_moments.jobs.handlers import build_handlers
from openworld_moments.media.probe import probe_file
from openworld_moments.media.process import ToolResult, run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo, ToolName
from openworld_moments.storage import Database, DerivedArtifactRepository
from tests.worker.conftest import wait_for


class Library:
    """A library with imported fixture clips and a DerivedMedia service."""

    def __init__(self, root: Path, tools: MediaTools) -> None:
        self.database = Database.open(root / "database.sqlite3")
        self.tools = tools
        self.derived = DerivedMedia(self.database, tools)
        self.root = root

    def add(self, source: Path) -> str:
        importer = Importer(self.database, self.tools)
        result = importer.run_import(
            {
                "paths": [str(source)],
                "mode": "reference",
                "recursive": False,
                "source_kind": "xbox",
            },
            job_id=new_id("job"),
            cancel=threading.Event(),
            progress=lambda *_: None,
            set_state=lambda _: None,
        )
        asset_id: str = result["items"][0]["asset_id"]
        return asset_id

    def generate(self, asset_id: str, **params: Any) -> dict[str, Any]:
        progress: list[tuple[int, int, str]] = []
        cancel = params.pop("cancel", threading.Event())
        result = self.derived.generate(
            {"asset_id": asset_id, **params},
            job_id=new_id("job"),
            cancel=cancel,
            progress=lambda d, t, m: progress.append((d, t, m)),
        )
        assert progress and all(0 <= d <= t for d, t, _ in progress)
        assert [d for d, _, _ in progress] == sorted(d for d, _, _ in progress)
        return result

    def status(self, asset_id: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            doc = self.derived.status_doc(conn, asset_id)
        load("derived-media", doc)  # contract-valid
        return doc

    def artifact(self, asset_id: str, kind: str) -> dict[str, Any]:
        doc = self.status(asset_id)
        found: dict[str, Any] = next(a for a in doc["artifacts"] if a["kind"] == kind)
        return found

    def path(self, artifact: dict[str, Any]) -> Path:
        return self.root.joinpath(*artifact["path"].split("/"))

    def staging_empty(self) -> bool:
        staging = self.root / "staging" / "derived"
        return not staging.exists() or not any(staging.iterdir())


@pytest.fixture
def library(tmp_path: Path, ffmpeg: ToolInfo, ffprobe: ToolInfo) -> Library:
    return Library(tmp_path / "library", MediaTools())


def _copy(media_dir: Path, name: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / name
    shutil.copyfile(media_dir / name, target)
    return target


def _identity(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


# -- fixture matrix -------------------------------------------------------------------


def test_sdr_proxy_thumbnails_and_waveform(
    library: Library, media_dir: Path, tmp_path: Path, ffprobe: ToolInfo
) -> None:
    source = _copy(media_dir, "h264_aac.mp4", tmp_path / "captures")
    before = _identity(source)
    asset = library.add(source)
    result = library.generate(asset, proxy_policy="always")
    assert result["outcomes"] == {
        "proxy": "generated",
        "filmstrip": "generated",
        "waveform": "generated",
    }
    assert [r["code"] for r in result["proxy_decision"]["reasons"]] == ["requested"]
    assert _identity(source) == before  # the original is never touched

    proxy = library.artifact(asset, "proxy")
    assert proxy["status"] == "ready" and proxy["proxy"]["tone_mapped"] is False
    probe = probe_file(library.path(proxy), ffprobe)
    assert probe["video"]["codec"] == "h264" and probe["video"]["pixel_format"] == "yuv420p"
    assert (probe["video"]["width"], probe["video"]["height"]) == (320, 180)
    assert probe["audio"][0]["codec"] == "aac" and probe["audio"][0]["channels"] == 2
    assert abs(probe["duration_ms"] - 1000) <= 250
    assert library.path(proxy).read_bytes()[4:8] == b"ftyp"
    assert proxy["sha256"] == hashlib.sha256(library.path(proxy).read_bytes()).hexdigest()

    film = library.artifact(asset, "filmstrip")
    assert film["filmstrip"]["source"] == "proxy" and film["filmstrip"]["times_ms"] == [500]
    frames = sorted(library.path(film).iterdir())
    assert [f.name for f in frames] == ["0001.jpg"]
    assert frames[0].read_bytes()[:3] == b"\xff\xd8\xff"

    wave = library.artifact(asset, "waveform")
    parsed = waveform.parse(library.path(wave).read_bytes())
    assert len(parsed.peaks) == wave["waveform"]["bucket_count"]
    assert 45 <= len(parsed.peaks) <= 55  # ~1 s at 50 buckets per second
    # FFmpeg's sine source plays at 1/8 of full scale: peak ~32 of 255 before AAC, and a
    # sine's RMS is ~0.7 of its peak.
    # The first and last buckets may be partial or hold encoder padding.
    peaks, rms = parsed.peaks[1:-1], parsed.rms[1:-1]
    assert min(peaks) >= 15 and max(peaks) <= 40
    assert all(0.5 * p <= r <= 0.8 * p for p, r in zip(peaks, rms, strict=True))
    assert library.staging_empty()


def test_hdr_source_gets_a_tone_mapped_sdr_proxy(
    library: Library, media_dir: Path, tmp_path: Path, ffprobe: ToolInfo
) -> None:
    source = _copy(media_dir, "hdr_pq.mp4", tmp_path / "captures")
    before = _identity(source)
    asset = library.add(source)
    result = library.generate(asset)
    assert "hdr" in [r["code"] for r in result["proxy_decision"]["reasons"]]
    proxy = library.artifact(asset, "proxy")
    info = proxy["proxy"]
    assert info["tone_mapped"] is True
    tone = info["tone_map"]
    assert tone["transfer"] == "smpte2084" and tone["method"] == "lut3d"
    assert tone["curve"] == "hable" and tone["output_transfer"] == "bt709"
    assert proxy["recipe"]["tone_map"] == tone  # recorded in the recipe, part of the key
    color = probe_file(library.path(proxy), ffprobe)["video"]["color"]
    assert color["transfer"] == "bt709" and color["primaries"] == "bt709"
    assert color["hdr"] is False
    original = probe_file(source, ffprobe)["video"]["color"]
    assert original["transfer"] == "smpte2084"  # the source keeps its HDR signal
    assert _identity(source) == before


def test_silent_clip_has_no_waveform_and_needs_no_proxy(
    library: Library, media_dir: Path, tmp_path: Path
) -> None:
    asset = library.add(_copy(media_dir, "no_audio.mp4", tmp_path / "captures"))
    result = library.generate(asset)
    assert result["outcomes"] == {
        "proxy": "not_needed",
        "filmstrip": "generated",
        "waveform": "not_applicable",
    }
    statuses = {a["kind"]: a["status"] for a in library.status(asset)["artifacts"]}
    assert statuses == {"proxy": "not_needed", "filmstrip": "ready", "waveform": "not_applicable"}
    film = library.artifact(asset, "filmstrip")
    assert film["filmstrip"]["source"] == "original"


def test_silent_clip_proxy_has_no_audio(
    library: Library, media_dir: Path, tmp_path: Path, ffprobe: ToolInfo
) -> None:
    asset = library.add(_copy(media_dir, "no_audio.mp4", tmp_path / "captures"))
    library.generate(asset, proxy_policy="always", artifacts=["proxy"])
    proxy = library.artifact(asset, "proxy")
    assert proxy["proxy"]["audio"] is False
    assert probe_file(library.path(proxy), ffprobe)["audio"] == []


def test_rotated_clip_proxy_is_upright(
    library: Library, media_dir: Path, tmp_path: Path, ffprobe: ToolInfo
) -> None:
    asset = library.add(_copy(media_dir, "rotated.mp4", tmp_path / "captures"))
    library.generate(asset, proxy_policy="always")
    proxy = library.artifact(asset, "proxy")
    video = probe_file(library.path(proxy), ffprobe)["video"]
    assert (video["width"], video["height"]) == (180, 320)
    assert video.get("rotation") in (None, 0)
    film = library.artifact(asset, "filmstrip")["filmstrip"]
    assert (film["width"], film["height"]) == (90, 160)


def test_vfr_clip_keeps_its_timing(
    library: Library, media_dir: Path, tmp_path: Path, ffprobe: ToolInfo
) -> None:
    source = _copy(media_dir, "vfr.mp4", tmp_path / "captures")
    asset = library.add(source)
    library.generate(asset, proxy_policy="always")
    proxy = library.artifact(asset, "proxy")
    assert proxy["proxy"]["frame_rate"] == "source"
    made = probe_file(library.path(proxy), ffprobe)
    original = probe_file(source, ffprobe)
    assert abs(made["duration_ms"] - original["duration_ms"]) <= 100


def test_hevc_and_matroska_get_proxies(library: Library, media_dir: Path, tmp_path: Path) -> None:
    for name, code in (("h264_aac.mkv", "container"), ("hevc.mp4", "codec")):
        if not (media_dir / name).exists():
            continue  # FFmpeg without libx265
        asset = library.add(_copy(media_dir, name, tmp_path / name.replace(".", "_")))
        result = library.generate(asset, artifacts=["proxy"])
        assert result["outcomes"] == {"proxy": "generated"}
        assert code in [r["code"] for r in result["proxy_decision"]["reasons"]]


# -- determinism, cache, invalidation, rebuild ----------------------------------------


def test_regeneration_is_deterministic(library: Library, media_dir: Path, tmp_path: Path) -> None:
    asset = library.add(_copy(media_dir, "hdr_pq.mp4", tmp_path / "captures"))
    library.generate(asset)
    first = {a["kind"]: (a["sha256"], a["path"]) for a in library.status(asset)["artifacts"]}
    library.generate(asset, force=True)
    second = {a["kind"]: (a["sha256"], a["path"]) for a in library.status(asset)["artifacts"]}
    assert first == second


def test_current_artifacts_are_cache_hits(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mp4", tmp_path / "captures"))
    library.generate(asset, proxy_policy="always")
    mtimes = {
        a["kind"]: library.path(a).stat().st_mtime_ns for a in library.status(asset)["artifacts"]
    }

    def no_ffmpeg(*_: Any, **__: Any) -> None:
        raise AssertionError("FFmpeg must not run for a cache hit")

    monkeypatch.setattr("openworld_moments.derived.service.run_tool", no_ffmpeg)
    result = library.generate(asset)  # 'auto' keeps the existing proxy current
    assert result["outcomes"] == {"proxy": "cached", "filmstrip": "cached", "waveform": "cached"}
    after = {
        a["kind"]: library.path(a).stat().st_mtime_ns for a in library.status(asset)["artifacts"]
    }
    assert after == mtimes


def test_preset_change_makes_artifacts_stale_and_regenerates(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "hdr_pq.mp4", tmp_path / "captures"))
    library.generate(asset)
    old = library.artifact(asset, "proxy")
    old_path = library.path(old)

    monkeypatch.setitem(recipes.PROXY_PRESET, "version", recipes.PROXY_PRESET["version"] + 1)
    statuses = {a["kind"]: a["status"] for a in library.status(asset)["artifacts"]}
    # The filmstrip is taken from the proxy, so it is stale too; the waveform is not.
    assert statuses == {"proxy": "stale", "filmstrip": "stale", "waveform": "ready"}
    result = library.generate(asset)
    assert result["outcomes"] == {
        "proxy": "generated",
        "filmstrip": "generated",
        "waveform": "cached",
    }
    new = library.artifact(asset, "proxy")
    assert new["status"] == "ready" and new["cache_key"] != old["cache_key"]
    assert new["path"] != old["path"] and not old_path.exists()  # old version removed


def test_toolchain_change_makes_artifacts_stale(
    library: Library, media_dir: Path, tmp_path: Path, ffmpeg: ToolInfo
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mkv", tmp_path / "captures"))
    library.generate(asset, artifacts=["waveform"])
    assert library.artifact(asset, "waveform")["status"] == "ready"

    class Upgraded(MediaTools):
        def tool(self, name: ToolName) -> ToolInfo:
            found = super().tool(name)
            if name != "ffmpeg":
                return found
            libraries = {**found.libraries, "libavcodec": "99.0.100"}
            return ToolInfo("ffmpeg", found.command, "test", "ok", "99.0", libraries)

    library.derived = DerivedMedia(library.database, Upgraded())
    assert library.artifact(asset, "waveform")["status"] == "stale"


def test_missing_files_are_rebuilt(library: Library, media_dir: Path, tmp_path: Path) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mp4", tmp_path / "captures"))
    library.generate(asset, proxy_policy="always")
    proxy = library.artifact(asset, "proxy")
    film = library.artifact(asset, "filmstrip")
    library.path(proxy).unlink()
    shutil.rmtree(library.path(film))
    statuses = {a["kind"]: a["status"] for a in library.status(asset)["artifacts"]}
    assert statuses == {"proxy": "missing", "filmstrip": "missing", "waveform": "ready"}
    result = library.generate(asset)
    assert result["outcomes"] == {
        "proxy": "generated",
        "filmstrip": "generated",
        "waveform": "cached",
    }
    rebuilt = library.artifact(asset, "proxy")
    assert rebuilt["sha256"] == proxy["sha256"] and library.path(rebuilt).is_file()


# -- cancellation and failures --------------------------------------------------------


def test_cancelling_leaves_no_partial_output(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "hdr_pq.mp4", tmp_path / "captures"))
    cancel = threading.Event()
    real = run_tool
    seen: dict[str, Path] = {}

    def cancel_mid_run(argv: list[str], **kwargs: Any) -> ToolResult:
        if kwargs.get("cwd") is not None:
            seen["staging"] = kwargs["cwd"]
            cancel.set()  # as if the user pressed Cancel while FFmpeg runs
        return real(argv, **kwargs)

    monkeypatch.setattr("openworld_moments.derived.service.run_tool", cancel_mid_run)
    with pytest.raises(DerivedCancelled):
        library.generate(asset, cancel=cancel)
    assert "staging" in seen and not seen["staging"].exists()
    assert library.staging_empty()
    derived = library.root / "derived"
    assert not derived.exists() or not any(derived.rglob("*.*"))
    assert library.artifact(asset, "proxy")["status"] == "not_generated"


def test_write_failure_is_retryable_and_leaves_nothing(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mkv", tmp_path / "captures"))

    def disk_full(built: Path, target: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(service, "promote_file", disk_full)
    with pytest.raises(DerivedFailure) as caught:
        library.generate(asset, artifacts=["proxy"])
    assert caught.value.code == "derived.disk_full" and caught.value.retryable
    assert library.staging_empty()
    derived = library.root / "derived"
    assert not derived.exists() or not any(p.is_file() for p in derived.rglob("*"))
    proxy = library.artifact(asset, "proxy")
    assert proxy["status"] == "failed" and proxy["last_error"]["code"] == "derived.disk_full"

    monkeypatch.undo()
    assert library.generate(asset, artifacts=["proxy"])["outcomes"] == {"proxy": "generated"}
    assert "last_error" not in library.artifact(asset, "proxy")


def test_failed_regeneration_keeps_the_previous_artifact(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mkv", tmp_path / "captures"))
    library.generate(asset, artifacts=["proxy"])
    good = library.artifact(asset, "proxy")

    def broken(argv: list[str], **kwargs: Any) -> ToolResult:
        return ToolResult(1, b"", "Error writing trailer: No space left on device")

    monkeypatch.setattr("openworld_moments.derived.service.run_tool", broken)
    with pytest.raises(DerivedFailure) as caught:
        library.generate(asset, artifacts=["proxy"], force=True)
    assert caught.value.code == "derived.disk_full"
    kept = library.artifact(asset, "proxy")
    assert kept["status"] == "ready" and kept["path"] == good["path"]
    assert kept["last_error"]["code"] == "derived.disk_full"
    assert library.path(kept).is_file()


def test_low_free_space_is_refused_before_work(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mkv", tmp_path / "captures"))
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        "openworld_moments.derived.service.shutil.disk_usage",
        lambda _: type(usage)(usage.total, usage.total, 1024),
    )
    with pytest.raises(DerivedFailure) as caught:
        library.generate(asset, artifacts=["waveform"])
    assert caught.value.code == "derived.disk_full"
    assert caught.value.details and caught.value.details["free_bytes"] == 1024


def test_ffmpeg_errors_are_reported_without_paths(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _copy(media_dir, "h264_aac.mkv", tmp_path / "secret captures")
    asset = library.add(source)
    real = run_tool

    def fail(argv: list[str], **kwargs: Any) -> ToolResult:
        # Broken arguments make the real FFmpeg fail; its stderr names the input.
        return real([*argv[:-1], "-c:v", "no_such_encoder", argv[-1]], **kwargs)

    monkeypatch.setattr("openworld_moments.derived.service.run_tool", fail)
    with pytest.raises(DerivedFailure) as caught:
        library.generate(asset, artifacts=["proxy"])
    assert caught.value.code == "derived.ffmpeg_failed" and not caught.value.retryable
    assert str(source) not in caught.value.stderr_tail
    assert "secret captures" not in caught.value.message


def test_bad_proxy_is_caught_by_validation(
    library: Library, media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mkv", tmp_path / "captures"))
    real = recipes.proxy_filter
    # A filter bug that crushes the picture to black: sampled decodes must catch it.
    monkeypatch.setattr(
        recipes, "proxy_filter", lambda *a, **k: real(*a, **k) + ",lutyuv=y=16:u=128:v=128"
    )
    with pytest.raises(DerivedFailure) as caught:
        library.generate(asset, artifacts=["proxy"])
    assert caught.value.code == "derived.validation_failed"
    assert library.artifact(asset, "proxy")["status"] == "failed"
    derived = library.root / "derived"
    assert not derived.exists() or not any(p.is_file() for p in derived.rglob("*"))


def test_unavailable_source(library: Library, media_dir: Path, tmp_path: Path) -> None:
    source = _copy(media_dir, "h264_aac.mkv", tmp_path / "captures")
    asset = library.add(source)
    source.unlink()
    with pytest.raises(DerivedFailure) as caught:
        library.generate(asset)
    assert caught.value.code == "derived.source_unavailable" and caught.value.retryable


def test_cleanup_removes_only_unreferenced_files(
    library: Library, media_dir: Path, tmp_path: Path
) -> None:
    asset = library.add(_copy(media_dir, "h264_aac.mp4", tmp_path / "captures"))
    library.generate(asset, proxy_policy="always")
    orphan = library.root / "derived" / asset / "proxy-0000000000000000.mp4"
    orphan.write_bytes(b"left over by a crash")
    report = library.derived.cleanup()
    assert report["removed_files"] == 1 and not orphan.exists()
    assert all(a["status"] == "ready" for a in library.status(asset)["artifacts"])
    with contextlib.closing(library.database.connect()) as conn:
        assert len(DerivedArtifactRepository(conn).relpaths()) == 3


# -- API and job ----------------------------------------------------------------------


@pytest.fixture
def api(
    tmp_path: Path, ffmpeg: ToolInfo, ffprobe: ToolInfo
) -> Iterator[tuple[TestClient, Library]]:
    token = secrets.token_hex(32)
    library = Library(tmp_path / "library", MediaTools())
    settings = ApiSettings(
        token=token, allowed_hosts=frozenset({"testserver"}), require_loopback_peer=False
    )
    handlers = build_handlers(library.tools, database=library.database, derived=library.derived)
    app = create_app(JobEngine(library.database, handlers), settings, derived=library.derived)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, library


def test_derived_endpoints_and_job(
    api: tuple[TestClient, Library], media_dir: Path, tmp_path: Path
) -> None:
    client, library = api
    asset = library.add(_copy(media_dir, "hdr_pq.mp4", tmp_path / "captures"))
    status = client.get(f"/v1/assets/{asset}/derived")
    assert status.status_code == 200
    assert {a["status"] for a in status.json()["artifacts"]} == {"not_generated"}

    body = {"idempotency_key": f"derive:{asset}"}
    created = client.post(f"/v1/assets/{asset}/derived", json=body)
    assert created.status_code == 201, created.text
    assert client.post(f"/v1/assets/{asset}/derived", json=body).status_code == 200  # same job
    job_id = created.json()["id"]

    def done() -> dict[str, Any] | None:
        job: dict[str, Any] = client.get(f"/v1/jobs/{job_id}").json()
        return job if job["state"] in ("ready", "failed", "cancelled") else None

    job = wait_for(done, timeout=60)
    load("job", job)
    assert job["kind"] == "proxy" and job["state"] == "ready", job
    assert job["result"]["outcomes"]["proxy"] == "generated"
    doc = client.get(f"/v1/assets/{asset}/derived").json()
    load("derived-media", doc)
    assert {a["status"] for a in doc["artifacts"]} == {"ready"}
    assert client.post("/v1/derived/cleanup").json()["removed_files"] == 0

    assert client.get("/v1/assets/ast_01JCBQ00000000000000000099/derived").status_code == 404
    bad = client.post(f"/v1/assets/{asset}/derived", json={"artifacts": ["frames"]})
    assert bad.status_code == 422
    assert client.post(f"/v1/assets/{asset}/derived", json={"path": "/x"}).status_code == 422


# -- host media lookup (M09) ----------------------------------------------------------


def test_media_lookup_serves_only_checked_files(
    library: Library, media_dir: Path, tmp_path: Path
) -> None:
    from openworld_moments.derived.service import MediaUnavailable

    source = _copy(media_dir, "h264_aac.mkv", tmp_path / "captures")
    asset = library.add(source)
    lookup = library.derived.media_file

    with contextlib.closing(library.database.connect()) as conn:
        original = lookup(conn, asset, "original")
        assert Path(original["path"]) == source
        assert original["content_type"] == "video/x-matroska"
        assert original["size_bytes"] == source.stat().st_size
        with pytest.raises(MediaUnavailable) as caught:
            lookup(conn, asset, "proxy")
        assert caught.value.code == "derived.not_ready"

    library.generate(asset)
    with contextlib.closing(library.database.connect()) as conn:
        proxy = lookup(conn, asset, "proxy")
        assert proxy["content_type"] == "video/mp4"
        assert Path(proxy["path"]).is_relative_to(library.root / "derived" / asset)
        thumb = lookup(conn, asset, "thumbnail", 1)
        assert thumb["content_type"] == "image/jpeg" and thumb["path"].endswith("0001.jpg")
        assert lookup(conn, asset, "waveform")["size_bytes"] > 16
        for variant, index in (
            ("thumbnail", 0),
            ("thumbnail", 2),
            ("thumbnail", None),
            ("frames", None),
        ):
            with pytest.raises(MediaUnavailable) as caught:
                lookup(conn, asset, variant, index)
            assert caught.value.code == "media.unknown_variant"

    source.unlink()  # moved away: the original is reported missing, the proxy still serves
    with contextlib.closing(library.database.connect()) as conn:
        with pytest.raises(MediaUnavailable) as caught:
            lookup(conn, asset, "original")
        assert caught.value.code == "media.source_missing"
        assert lookup(conn, asset, "proxy")["size_bytes"] > 0


def test_media_endpoint(api: tuple[TestClient, Library], media_dir: Path, tmp_path: Path) -> None:
    client, library = api
    asset = library.add(_copy(media_dir, "h264_aac.mp4", tmp_path / "captures"))
    found = client.get(f"/v1/assets/{asset}/media/original")
    assert found.status_code == 200 and found.json()["content_type"] == "video/mp4"
    missing = client.get(f"/v1/assets/{asset}/media/proxy")
    assert missing.status_code == 404 and missing.json()["code"] == "derived.not_ready"
    assert client.get(f"/v1/assets/{asset}/media/../../x").status_code == 404
    unknown = client.get("/v1/assets/ast_01JCBQ00000000000000000099/media/original")
    assert unknown.status_code == 404 and unknown.json()["code"] == "asset.not_found"
