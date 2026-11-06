# SPDX-License-Identifier: AGPL-3.0-or-later
"""Derived media building blocks that need no FFmpeg (M08): proxy policy, tone map,
waveform format, recipes and cache keys, layout and cleanup, request validation."""

from __future__ import annotations

import itertools
import os
import struct
import sys
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts.generated.media_asset_schema import MediaAsset

from openworld_moments.derived import recipes, tonemap, waveform
from openworld_moments.derived.layout import CleanupReport, DerivedPaths, fsync_file, remove_entry
from openworld_moments.derived.policy import decide, fit, proxy_geometry, thumbnail_size
from openworld_moments.derived.service import _ProgressParser
from openworld_moments.jobs.handlers import validate_derived
from openworld_moments.media.tools import ToolInfo

ASSET = "ast_01JCBQ00000000000000000001"
KEY = "ab" * 32


def _asset(**video: Any) -> MediaAsset:
    audio = video.pop("audio", [{"codec": "aac", "channels": 2, "sample_rate_hz": 48000}])
    container = video.pop("container", "mov,mp4,m4a,3gp,3g2,mj2")
    base: dict[str, Any] = {
        "codec": "h264",
        "width": 1920,
        "height": 1080,
        "frame_rate": {"num": 60, "den": 1},
        "pixel_format": "yuv420p",
        "color": {"hdr": False},
    }
    base.update(video)
    return MediaAsset.model_validate(
        {
            "schema_version": "1.6",
            "id": ASSET,
            "sha256": "cd" * 32,
            "original_name": "clip.mp4",
            "source_kind": "xbox",
            "import_mode": "reference",
            "duration_ms": 61_500,
            "container": container,
            "video": base,
            "audio": audio,
            "created_at": "2026-11-21T09:00:00Z",
        }
    )


def _ffmpeg(version: str = "7.1.1") -> ToolInfo:
    return ToolInfo("ffmpeg", ("ffmpeg",), "test", "ok", version, {"libavcodec": "61.19.101"})


# -- policy ---------------------------------------------------------------------------


def test_xbox_style_sdr_clip_needs_no_proxy() -> None:
    decision = decide(_asset())
    assert decision.needed is False and decision.reasons == ()
    assert decision.doc()["policy_version"] == 1


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"codec": "hevc"}, "codec"),
        ({"container": "matroska,webm"}, "container"),
        ({"pixel_format": "yuv420p10le"}, "pixel_format"),
        ({"color": {"hdr": True, "transfer": "smpte2084"}}, "hdr"),
        ({"color": {"hdr": False, "transfer": "arib-std-b67"}}, "hdr"),
        ({"width": 3840, "height": 2160}, "resolution"),
        ({"frame_rate": {"num": 120, "den": 1}}, "frame_rate"),
        ({"audio": [{"codec": "opus", "channels": 2, "sample_rate_hz": 48000}]}, "audio_codec"),
    ],
)
def test_each_unplayable_property_is_a_reason(change: dict[str, Any], code: str) -> None:
    decision = decide(_asset(**change))
    assert decision.needed is True
    assert [r.code for r in decision.reasons] == [code]
    assert decision.reasons[0].detail


def test_always_policy_explains_itself() -> None:
    decision = decide(_asset(), "always")
    assert decision.needed and [r.code for r in decision.reasons] == ["requested"]


def test_proxy_geometry() -> None:
    assert fit(3840, 2160, 1280) == (1280, 720)
    assert fit(1080, 1920, 1280) == (720, 1280)  # vertical: longer edge capped too
    assert fit(320, 180, 1280) == (320, 180)  # never upscaled
    odd = fit(321, 179, 1280)  # even sizes for 4:2:0, within a pixel
    assert all(v % 2 == 0 for v in odd) and abs(odd[0] - 321) <= 1 and abs(odd[1] - 179) <= 1
    rotated = proxy_geometry(_asset(width=1920, height=1080, rotation=90).video)  # type: ignore[arg-type]
    assert (rotated.width, rotated.height) == (720, 1280)
    assert proxy_geometry(_asset(frame_rate={"num": 120, "den": 1}).video).fps_cap == 60  # type: ignore[arg-type]
    assert proxy_geometry(_asset().video).fps_cap is None  # type: ignore[arg-type]
    hdr = proxy_geometry(_asset(color={"hdr": True}).video)  # type: ignore[arg-type]
    assert hdr.hdr_transfer == "smpte2084"  # flagged HDR without a transfer: HDR10
    assert thumbnail_size(1280, 720) == (160, 90)


# -- tone map -------------------------------------------------------------------------


def test_pq_tone_map_is_monotonic_and_bounded() -> None:
    settings = tonemap.ToneMapSettings("smpte2084")
    greys = [tonemap.map_pixel((v / 20, v / 20, v / 20), settings)[0] for v in range(21)]
    assert greys[0] == 0.0
    assert all(b >= a for a, b in itertools.pairwise(greys))
    assert all(0.0 <= g <= 1.0 for g in greys)
    # HDR reference white (203 nits, PQ ~0.58) lands in the upper SDR range, not clipped.
    white = tonemap.map_pixel((0.58, 0.58, 0.58), settings)[0]
    assert 0.6 < white < 0.85
    assert abs(tonemap.pq_to_nits(1.0) - 10000) < 1e-6


def test_hlg_tone_map_and_lut_determinism() -> None:
    settings = tonemap.ToneMapSettings("arib-std-b67")
    assert tonemap.map_pixel((0.0, 0.0, 0.0), settings) == (0.0, 0.0, 0.0)
    assert tonemap.map_pixel((1.0, 1.0, 1.0), settings)[0] > 0.95
    small = tonemap.ToneMapSettings("smpte2084", lut_size=5)
    text = tonemap.cube_text(small)
    assert text == tonemap.cube_text(small)  # byte-identical
    lines = text.splitlines()
    assert "LUT_3D_SIZE 5" in lines and len([ln for ln in lines if ln[:1].isdigit()]) == 125
    assert tonemap.lut_sha256(small) != tonemap.lut_sha256(settings)
    described = small.describe()
    assert described["lut_sha256"] == tonemap.lut_sha256(small) and described["version"] == 1
    with pytest.raises(ValueError, match="lut_size"):
        tonemap.cube_text(tonemap.ToneMapSettings("smpte2084", lut_size=1))


# -- waveform -------------------------------------------------------------------------


def _pcm(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_waveform_is_independent_of_chunking() -> None:
    samples = [(i * 37) % 65535 - 32767 for i in range(waveform.BUCKET_SAMPLES * 5 + 17)]
    data = _pcm(samples)
    whole = waveform.WaveformBuilder()
    whole.feed(data)
    pieces = waveform.WaveformBuilder()
    for start in range(0, len(data), 333):  # odd sizes split samples across chunks
        pieces.feed(data[start : start + 333])
    assert whole.finish() == pieces.finish()
    parsed = waveform.parse(whole.finish())
    assert len(parsed.peaks) == waveform.expected_buckets(len(samples)) == 6
    assert parsed.buckets_per_second == waveform.BUCKETS_PER_SECOND


def test_waveform_levels_and_header() -> None:
    builder = waveform.WaveformBuilder()
    builder.feed(_pcm([0] * waveform.BUCKET_SAMPLES + [-32768, 32767] * waveform.BUCKET_SAMPLES))
    parsed = waveform.parse(builder.finish())
    assert list(parsed.peaks) == [0, 255, 255]
    assert parsed.rms[0] == 0 and parsed.rms[1] == 255
    with pytest.raises(waveform.WaveformError):
        waveform.parse(b"OWMW")
    with pytest.raises(waveform.WaveformError):
        waveform.parse(b"XXXX" + bytes(12))
    good = builder.finish()
    with pytest.raises(waveform.WaveformError, match="length"):
        waveform.parse(good[:-1])


# -- recipes and cache keys -----------------------------------------------------------


def test_cache_key_covers_asset_kind_recipe_and_toolchain() -> None:
    asset = _asset(codec="hevc")
    geometry = proxy_geometry(asset.video)  # type: ignore[arg-type]
    recipe = recipes.proxy_recipe(_ffmpeg(), geometry, audio=True, source_range="tv", tone_map=None)
    key = recipes.cache_key("cd" * 32, "proxy", recipe)
    assert key == recipes.cache_key("cd" * 32, "proxy", dict(reversed(list(recipe.items()))))
    assert key != recipes.cache_key("ce" * 32, "proxy", recipe)
    assert key != recipes.cache_key("cd" * 32, "waveform", recipe)
    newer_tool = recipes.proxy_recipe(
        _ffmpeg("7.1.2"), geometry, audio=True, source_range="tv", tone_map=None
    )
    assert key != recipes.cache_key("cd" * 32, "proxy", newer_tool)
    bumped = {**recipe, "preset": {**recipe["preset"], "version": 2}}
    assert key != recipes.cache_key("cd" * 32, "proxy", bumped)


def test_commands_are_argument_lists_without_user_text_in_filters(tmp_path: Path) -> None:
    hostile = tmp_path / "it's, [weird]; =clip%d.mp4"
    asset = _asset(color={"hdr": True, "transfer": "smpte2084"})
    geometry = proxy_geometry(asset.video)  # type: ignore[arg-type]
    settings = tonemap.ToneMapSettings("smpte2084")
    argv = recipes.proxy_args(
        _ffmpeg(), hostile, geometry, audio=True, source_range="tv", tone_map=settings
    )
    assert argv[argv.index("-i") + 1] == f"file:{hostile}"
    assert argv[argv.index("-protocol_whitelist") + 1] == "file"
    graph = argv[argv.index("-vf") + 1]
    assert "lut3d=file=tonemap.cube" in graph and str(tmp_path) not in graph
    assert argv[-1] == recipes.PROXY_OUTPUT  # relative: FFmpeg runs in staging
    plan = recipes.filmstrip_plan(61_500, 160, 90)
    film = recipes.filmstrip_args(_ffmpeg(), hostile, plan, 61_500)
    assert film[-1] == "%04d.jpg" and str(tmp_path) not in film[film.index("-vf") + 1]
    wave = recipes.waveform_args(_ffmpeg(), hostile)
    assert wave[-1] == "pipe:1" and "-progress" not in wave
    silent = recipes.proxy_args(
        _ffmpeg(), hostile, geometry, audio=False, source_range="tv", tone_map=None
    )
    assert "-an" in silent and "0:a:0" not in silent


def test_filmstrip_plan_samples_the_middle_of_each_slice() -> None:
    plan = recipes.filmstrip_plan(61_500, 160, 90)
    assert plan.count == 13 and len(plan.times_ms) == 13
    assert plan.times_ms[0] == 61_500 // 26 and plan.times_ms[-1] < 61_500
    assert recipes.filmstrip_plan(1000, 160, 90).times_ms == (500,)
    assert recipes.filmstrip_plan(10 * 3600 * 1000, 160, 90).count == 120  # capped
    assert recipes.filmstrip_plan(0, 160, 90).count == 1


def test_progress_parser_reads_out_time() -> None:
    seen: list[int] = []
    parser = _ProgressParser(seen.append)
    parser.feed(b"frame=10\nout_time_us=1500")
    parser.feed(b"000\nout_time_ms=2000000\nout_time_us=N/A\nprogress=continue\n")
    assert seen == [1500, 2000]


# -- layout and cleanup ---------------------------------------------------------------


def test_stored_paths_are_checked(tmp_path: Path) -> None:
    paths = DerivedPaths(tmp_path)
    good = DerivedPaths.relpath(ASSET, "proxy", KEY)
    assert good == f"derived/{ASSET}/proxy-{KEY[:16]}.mp4"
    assert paths.resolve(good) == tmp_path / "derived" / ASSET / f"proxy-{KEY[:16]}.mp4"
    for bad in (
        f"derived/{ASSET}/../../database.sqlite3",
        "/etc/passwd",
        f"derived/{ASSET}/notes.txt",
        f"managed-media/{ASSET}/proxy-{KEY[:16]}.mp4",
        f"derived/ast_bad/proxy-{KEY[:16]}.mp4",
        f"derived/{ASSET}/sub/proxy-{KEY[:16]}.mp4",
        "",
    ):
        assert paths.resolve(bad) is None, bad
    with pytest.raises(ValueError):
        DerivedPaths.relpath("../x", "proxy", KEY)


def _symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except OSError:  # Windows without symlink rights
        pytest.skip("symlinks are not available")


def test_cleanup_keeps_current_artifacts_and_never_follows_links(tmp_path: Path) -> None:
    paths = DerivedPaths(tmp_path)
    keep = DerivedPaths.relpath(ASSET, "proxy", KEY)
    stale = DerivedPaths.relpath(ASSET, "waveform", KEY)
    for rel in (keep, stale):
        target = paths.resolve(rel)
        assert target is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 10)
    gone = tmp_path / "derived" / "ast_01JCBQ00000000000000000099"
    (gone / "filmstrip-0000000000000000").mkdir(parents=True)
    (gone / "filmstrip-0000000000000000" / "0001.jpg").write_bytes(b"y")
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.mp4").write_bytes(b"precious")
    _symlink(outside, tmp_path / "derived" / ASSET / "linked", directory=True)

    report = paths.cleanup([keep], [ASSET])
    assert paths.resolve(keep).is_file()  # type: ignore[union-attr]
    assert not paths.resolve(stale).exists()  # type: ignore[union-attr]
    assert not gone.exists()
    assert (outside / "keep.mp4").read_bytes() == b"precious"  # the link target survives
    assert not (tmp_path / "derived" / ASSET / "linked").exists()
    assert report.skipped_links == 1 and report.removed_files == 2
    assert report.freed_bytes == 11


def test_cleanup_ignores_a_linked_derived_root(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ASSET).mkdir(parents=True)
    (elsewhere / ASSET / "proxy-0000000000000000.mp4").write_bytes(b"z")
    library = tmp_path / "library"
    library.mkdir()
    _symlink(elsewhere, library / "derived", directory=True)
    report = DerivedPaths(library).cleanup([], [])
    assert report.removed_files == 0
    assert (elsewhere / ASSET / "proxy-0000000000000000.mp4").exists()


def test_fsync_file_flushes_without_changing_the_file(tmp_path: Path) -> None:
    # On Windows a flush needs a writable handle; the content must not change.
    target = tmp_path / "proxy.mp4"
    target.write_bytes(b"finished artifact")
    fsync_file(target)
    assert target.read_bytes() == b"finished artifact"


def test_remove_entry_refuses_paths_outside_its_root(tmp_path: Path) -> None:
    root = tmp_path / "derived"
    root.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("stay")
    report = CleanupReport()
    remove_entry(victim, report, inside=root)
    remove_entry(root / ".." / "victim.txt", report, inside=root)
    remove_entry(root, report, inside=root)  # the root itself is never removed
    assert victim.exists() and root.exists() and report.removed_files == 0


@pytest.mark.skipif(sys.platform != "win32", reason="junctions exist only on Windows")
def test_cleanup_removes_a_junction_without_entering_it(tmp_path: Path) -> None:
    import subprocess

    paths = DerivedPaths(tmp_path)
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.mp4").write_bytes(b"precious")
    (tmp_path / "derived" / ASSET).mkdir(parents=True)
    junction = tmp_path / "derived" / ASSET / "junction"
    cmd = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "cmd.exe")
    subprocess.run(  # noqa: S603 - fixed argument list
        [cmd, "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True
    )
    paths.cleanup([], [ASSET])
    assert (outside / "keep.mp4").exists() and not junction.exists()


# -- request validation ---------------------------------------------------------------


def test_request_validation() -> None:
    assert validate_derived({"asset_id": ASSET}) == {
        "asset_id": ASSET,
        "artifacts": ["proxy", "filmstrip", "waveform"],
        "proxy_policy": "auto",
        "force": False,
    }
    assert validate_derived({"asset_id": ASSET, "artifacts": ["waveform", "proxy"]})[
        "artifacts"
    ] == ["proxy", "waveform"]
    for bad in (
        {},
        {"asset_id": "nope"},
        {"asset_id": ASSET, "artifacts": []},
        {"asset_id": ASSET, "artifacts": ["proxy", "proxy"]},
        {"asset_id": ASSET, "artifacts": ["frames"]},
        {"asset_id": ASSET, "proxy_policy": "never"},
        {"asset_id": ASSET, "force": "yes"},
        {"asset_id": ASSET, "path": "/etc/passwd"},
    ):
        with pytest.raises(ValueError):
            validate_derived(bad)
