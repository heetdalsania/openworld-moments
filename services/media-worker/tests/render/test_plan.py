# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render IR and compiler (M24), without FFmpeg: argument safety, exact frame and
sample counts, crop/keyframe pieces, blur, gain/mute, text refusal, tone mapping,
limits, encoder arguments, presets and failure mapping."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from openworld_moments_contracts import load

from openworld_moments.derived.tonemap import ToneMapSettings
from openworld_moments.media.process import ToolResult
from openworld_moments.render import encoders as encoder_module
from openworld_moments.render.encoders import (
    CPU,
    ENCODERS,
    EncoderProbe,
    video_args,
    videotoolbox_quality,
)
from openworld_moments.render.plan import (
    MAX_PIECES,
    RenderError,
    SourceFacts,
    build_plan,
    graph_option,
    materialize,
)
from openworld_moments.render.presets import DEFAULT_PRESETS, PresetCatalog
from openworld_moments.render.service import estimate_bytes, failure_from_stderr

A = "ast_01JCBQ00000000000000000001"
B = "ast_01JCBQ00000000000000000002"
HOSTILE = '\'; rm -rf / #$(whoami) `id` "x" & | > C:\\Windows\\..\\evil'


def preset(**over: Any) -> dict[str, Any]:
    doc = json.loads((DEFAULT_PRESETS / "horizontal-1080p30.json").read_text("utf-8"))
    return {**doc, **over}


def segment(
    sid: int, aid: str, start: int, src_in: int, src_out: int, **crop: Any
) -> dict[str, Any]:
    return {
        "id": f"seg_01JCBQ000000000000000000{sid:02d}",
        "asset_id": aid,
        "source_in_ms": src_in,
        "source_out_ms": src_out,
        "timeline_start_ms": start,
        "crop": {"mode": crop.get("mode", "fit"), "keyframes": crop.get("keyframes", [])},
    }


def document(*segments: dict[str, Any], **project: Any) -> dict[str, Any]:
    return {
        "model_version": 1,
        "project": {
            "id": "prj_01JCBQ00000000000000000005",
            "title": HOSTILE,
            "tracks": [{"kind": "video", "segments": list(segments)}],
            "captions": project.get("captions", [{"start_ms": 0, "end_ms": 500, "text": HOSTILE}]),
            "overlays": project.get("overlays", []),
            "audio": project.get("audio", {"gain_db": 0, "mute_ranges": []}),
            **(
                {"caption_settings": project["caption_settings"]}
                if "caption_settings" in project
                else {}
            ),
        },
        "layout": {"aspect_ratio": "16:9"},
        "sources": [],
    }


FACTS = {
    A: SourceFacts(A, "a" * 64, HOSTILE + ".mp4", True, (60, 1), None),
    B: SourceFacts(B, "b" * 64, "クリップ é.mov", False, (30000, 1001), None),
}


def plan_for(doc: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return build_plan(
        doc,
        FACTS,
        kw.pop("preset", preset()),
        kw.pop("encoder", CPU),
        ffmpeg_version=kw.pop("ffmpeg", "7.1.1"),
        **kw,
    )


def record(plan: dict[str, Any]) -> object:
    return load(
        "render",
        {
            "schema_version": "1.18",
            "id": "job_01JCBQ00000000000000000041",
            "project_id": "prj_01JCBQ00000000000000000005",
            "status": "rendering",
            "preset_id": plan["preset"]["id"],
            "encoder": plan["encoder"]["id"],
            "created_at": "2026-11-08T10:00:00Z",
            "plan": plan,
        },
    )


def test_user_text_and_paths_never_enter_the_argument_array() -> None:
    plan = plan_for(document(segment(1, A, 0, 1000, 3500), segment(2, B, 2500, 0, 2000)))
    blob = json.dumps(plan["command"])
    assert HOSTILE not in blob and "クリップ" not in blob and "rm -rf" not in blob
    argv = plan["command"]["argv"]
    assert [a for a in argv if a.startswith("{")] == ["{source:0}", "{source:1}", "{output}"]
    hostile, unicode = Path("/lib/" + HOSTILE + ".mp4"), Path("/lib/クリップ é.mov")
    output = Path("/lib/staging/render.mp4")
    real = materialize(argv, [hostile, unicode], output)
    # Each path is exactly one argument, prefixed with the file protocol; nothing is joined.
    # Paths keep the platform's own separators (backslashes on Windows).
    assert f"file:{hostile}" in real and f"file:{unicode}" in real
    assert real[-1] == f"file:{output}"
    # HOSTILE contains separators that Windows normalizes, so count a separator-free part.
    assert real.count(f"file:{hostile}") == 1
    assert sum("rm -rf" in a for a in real) == 1 and sum("`id`" in a for a in real) == 1
    record(plan)  # the stored plan satisfies the contract


def test_frame_and_sample_counts_are_exact_and_drift_free() -> None:
    # Three 1001 ms pieces at 30 fps: per-piece rounding would drift; cumulative does not.
    doc = document(
        segment(1, A, 0, 0, 1001), segment(2, A, 1001, 2000, 3001), segment(3, A, 2002, 5000, 6001)
    )
    plan = plan_for(doc)
    assert plan["duration_ms"] == 3003
    assert [s["frames"] for s in plan["segments"]] == [30, 30, 30]
    assert sum(s["frames"] for s in plan["segments"]) == round(3003 * 30 / 1000)
    assert sum(s["samples"] for s in plan["segments"]) == 3003 * 48
    assert "trim=end_frame=30" in plan["command"]["filter_complex"]
    assert "atrim=end_sample=48048" in plan["command"]["filter_complex"]


def test_source_frame_rate_preset_uses_the_first_clip() -> None:
    plan = plan_for(
        document(segment(1, B, 0, 0, 2000), segment(2, A, 2000, 0, 1000)),
        preset=preset(id="horizontal-source-fps", fps="source"),
    )
    assert plan["output"]["fps"] == {"num": 30000, "den": 1001}
    assert "fps=30000/1001" in plan["command"]["filter_complex"]


def test_crop_keyframes_hold_and_split_the_segment() -> None:
    keyframes = [
        {"at_ms": 0, "region": [0.0, 0.0, 0.5, 0.5]},
        {"at_ms": 1000, "region": [0.5, 0.5, 0.5, 0.5]},
    ]
    plan = plan_for(document(segment(1, A, 0, 2000, 4000, mode="manual", keyframes=keyframes)))
    pieces = plan["segments"]
    assert [(p["in_ms"], p["out_ms"], p["timeline_start_ms"]) for p in pieces] == [
        (2000, 3000, 0),
        (3000, 4000, 1000),
    ]
    assert [p["crop"]["region"] for p in pieces] == [[0.0, 0.0, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]]
    graph = plan["command"]["filter_complex"]
    assert "crop=w=iw*0.500000:h=ih*0.500000:x=iw*0.500000:y=ih*0.500000:exact=1" in graph


def test_fill_crops_to_cover_and_fit_letterboxes() -> None:
    plan = plan_for(document(segment(1, A, 0, 0, 1000, mode="fill"), segment(2, A, 1000, 0, 1000)))
    graph = plan["command"]["filter_complex"]
    assert "force_original_aspect_ratio=increase:flags=bicubic,crop=1920:1080" in graph
    assert "force_original_aspect_ratio=decrease" in graph and "pad=1920:1080" in graph


def test_safe_layout_renders_as_fit_with_a_visible_note() -> None:
    plan = plan_for(document(segment(1, A, 0, 0, 1000, mode="safe")))
    assert plan["segments"][0]["crop"]["mode"] == "safe"
    assert any("M25" in n for n in plan["notes"])


def test_blur_regions_become_clamped_pixel_rectangles_with_time_enable() -> None:
    blur = {"kind": "blur", "start_ms": 500, "end_ms": 1500, "region": [0.999, 0.999, 0.001, 0.001]}
    plan = plan_for(document(segment(1, A, 0, 0, 2000), overlays=[blur]))
    graph = plan["command"]["filter_complex"]
    # A tiny region at the corner grows to the 8 px minimum and stays inside the frame.
    assert "crop=w=8:h=8:" in graph
    assert "min(1912,floor(" in graph and "min(1072,floor(" in graph
    assert "eval=frame:enable='gte(t,0.500)*lt(t,1.500)'[vout]" in graph
    assert plan["blur_overlays"] == [{"start_ms": 500, "end_ms": 1500, "region": blur["region"]}]


def test_gain_ranges_override_project_gain_and_mute_dominates() -> None:
    audio = {
        "gain_db": -3,
        "gain_ranges": [{"start_ms": 0, "end_ms": 1000, "gain_db": 6}],
        "mute_ranges": [{"start_ms": 500, "end_ms": 700}],
    }
    graph = plan_for(document(segment(1, A, 0, 0, 2000), audio=audio))["command"]["filter_complex"]
    chain = graph.split("[ac]")[-1]
    assert (
        chain.index("volume=volume=-3dB:enable='not(between(t,0.000,1.000))'")
        < chain.index("volume=volume=6dB:enable='between(t,0.000,1.000)'")
        < chain.index("volume=volume=0:enable='between(t,0.500,0.700)'")
    )
    assert "asetnsamples=n=480" in chain


def test_projects_without_audio_render_video_only_and_silent_pieces_are_filled() -> None:
    silent = plan_for(document(segment(1, B, 0, 0, 1000)))
    assert silent["output"]["audio"] is False and "-an" in silent["command"]["argv"]
    mixed = plan_for(document(segment(1, A, 0, 0, 1000), segment(2, B, 1000, 0, 1000)))
    assert mixed["output"]["audio"] is True
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in mixed["command"]["argv"]


def test_text_is_refused_unless_explicitly_omitted() -> None:
    text = {"kind": "text", "start_ms": 0, "end_ms": 500, "region": [0, 0, 1, 0.1], "text": HOSTILE}
    settings = {
        "preset": "compact",
        "region": [0.1, 0.8, 0.8, 0.1],
        "burn_in": True,
        "sidecar": "none",
    }
    doc = document(segment(1, A, 0, 0, 1000), overlays=[text], caption_settings=settings)
    with pytest.raises(RenderError) as caught:
        plan_for(doc)
    assert caught.value.code == "render.text_unsupported"
    assert caught.value.details == {"omitted": ["text_overlays", "burned_captions"]}
    plan = plan_for(doc, omit_text=True)
    assert plan["omitted"] == ["text_overlays", "burned_captions"]
    assert any("left out" in n for n in plan["notes"])
    assert HOSTILE not in json.dumps(plan["command"])


def test_hdr_sources_are_tone_mapped_with_the_m08_lut() -> None:
    facts = {A: SourceFacts(A, "a" * 64, "hdr.mov", True, (60, 1), ToneMapSettings("smpte2084"))}
    plan = build_plan(document(segment(1, A, 0, 0, 1000)), facts, preset(), CPU, ffmpeg_version="7")
    assert plan["sources"][0]["tone_mapped"] is True
    assert "lut3d=file=tonemap-pq.cube:interp=tetrahedral" in plan["command"]["filter_complex"]
    assert any("HDR" in n for n in plan["notes"])


def test_limits_and_empty_projects_are_refused_clearly() -> None:
    with pytest.raises(RenderError, match="at least one clip"):
        plan_for(document())
    many = [segment(i % 90 + 1, A, i * 100, 0, 100) for i in range(MAX_PIECES + 1)]
    with pytest.raises(RenderError) as caught:
        plan_for(document(*many))
    assert caught.value.code == "render.too_complex"
    with pytest.raises(RenderError, match=r"H\.264"):
        plan_for(
            document(segment(1, A, 0, 0, 1000)), preset=preset(video={"codec": "hevc", "crf": 20})
        )


def test_graph_is_read_from_a_file_with_the_right_option_for_the_ffmpeg_version() -> None:
    assert graph_option("6.1.1-3ubuntu5") == ["-filter_complex_script", "graph.txt"]
    assert graph_option("n6.0") == ["-filter_complex_script", "graph.txt"]
    assert graph_option("7.1.1") == ["-/filter_complex", "graph.txt"]
    assert graph_option("unknown") == ["-filter_complex_script", "graph.txt"]


def test_windows_argument_length_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openworld_moments.render.plan.sys.platform", "win32")
    plan = plan_for(document(*[segment(i + 1, A, i * 100, 0, 100) for i in range(60)]))
    with pytest.raises(RenderError, match="Windows"):
        materialize(plan["command"]["argv"], [Path("C:/" + "x" * 600)], Path("C:/out.mp4"))


def test_encoder_arguments_and_quality_mapping() -> None:
    crf = {"video": {"codec": "h264", "crf": 20}}
    rate = {"video": {"codec": "h264", "bitrate_kbps": 4000}}
    assert video_args(CPU, crf)[:8] == [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-profile:v",
        "high",
        "-crf",
        "20",
    ]
    assert "-maxrate" in video_args(CPU, rate) and "-crf" not in video_args(CPU, rate)
    assert videotoolbox_quality(20) == 65 and videotoolbox_quality(0) == 100
    assert videotoolbox_quality(51) == 11
    assert video_args(ENCODERS["h264_nvenc"], crf)[-6:] == ["-rc", "vbr", "-cq", "20", "-b:v", "0"]
    assert "-global_quality" in video_args(ENCODERS["h264_qsv"], crf)
    assert "-qp_i" in video_args(ENCODERS["h264_amf"], crf)
    hardware = plan_for(document(segment(1, A, 0, 0, 1000)), encoder=ENCODERS["h264_videotoolbox"])
    assert hardware["encoder"] == {
        "id": "h264_videotoolbox",
        "kind": "hardware",
        "quality_note": ENCODERS["h264_videotoolbox"].quality_note,
    }


def test_probe_requires_a_real_test_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    listing = b" V....D libx264  x\n V....D h264_videotoolbox  y\n V....D h264_nvenc  z\n"

    def fake_run(argv: list[str], **_: Any) -> ToolResult:
        calls.append(argv)
        if "-encoders" in argv:
            return ToolResult(0, listing, "")
        return ToolResult(1 if "h264_nvenc" in argv else 0, b"", "")

    monkeypatch.setattr(encoder_module, "run_tool", fake_run)
    from openworld_moments.media.tools import ToolInfo

    tool = ToolInfo(name="ffmpeg", command=("ffmpeg",), source="test", status="ok", version="7.1.1")
    statuses = {s["id"]: s for s in EncoderProbe().status(tool)}
    assert statuses["libx264"]["available"] and statuses["h264_videotoolbox"]["available"]
    assert not statuses["h264_nvenc"]["available"]
    assert "test encode failed" in statuses["h264_nvenc"]["reason"]
    assert statuses["h264_qsv"]["reason"] == "Not built into this FFmpeg."
    encodes = [c for c in calls if "testsrc2=size=320x240:rate=30:duration=0.5" in c]
    assert len(encodes) == 3  # every built encoder is actually exercised
    before = len(calls)
    EncoderProbe.status  # noqa: B018 - cached per FFmpeg version below
    probe = EncoderProbe()
    probe.status(tool)
    probe.status(tool)
    assert len(calls) - before == 4  # one listing + three encodes, then cached


def test_failure_mapping_offers_cpu_fallback_only_for_hardware() -> None:
    hw = failure_from_stderr("Error while opening encoder", ENCODERS["h264_nvenc"])
    assert hw.code == "render.hardware_encoder_failed"
    assert hw.details == {"fallback_encoder": "libx264"}
    assert failure_from_stderr("Error", CPU).code == "render.encode_failed"
    assert failure_from_stderr(
        "av_interleaved_write_frame(): No space left on device", CPU
    ).code == ("render.disk_full")


def test_output_estimate_scales_with_duration_and_bitrate() -> None:
    plan = plan_for(document(segment(1, A, 0, 0, 10_000)))
    crf = estimate_bytes(plan)
    assert 5_000_000 < crf < 20_000_000
    rate = copy.deepcopy(plan)
    rate["preset"]["video"] = {"codec": "h264", "bitrate_kbps": 8000}
    assert estimate_bytes(rate) == int(10 * (8_000_000 + 192_000) / 8 * 1.25)


def test_shipped_presets_are_valid_and_bad_files_are_ignored(tmp_path: Path) -> None:
    shipped = {p["id"] for p in PresetCatalog().all()}
    assert shipped == {
        "horizontal-1080p30",
        "horizontal-source-fps",
        "horizontal-720p30",
        "vertical-1080x1920-30",
        "vertical-source-fps",
    }
    good = json.loads((DEFAULT_PRESETS / "horizontal-720p30.json").read_text("utf-8"))
    (tmp_path / "horizontal-720p30.json").write_text(json.dumps(good), "utf-8")
    (tmp_path / "renamed.json").write_text(json.dumps(good), "utf-8")  # id mismatch
    (tmp_path / "hevc.json").write_text(
        json.dumps({**good, "id": "hevc", "video": {"codec": "hevc", "crf": 20}}), "utf-8"
    )
    (tmp_path / "broken.json").write_text("{", "utf-8")
    (tmp_path / "odd.json").write_text(json.dumps({**good, "id": "odd", "width": 1281}), "utf-8")
    catalog = PresetCatalog(tmp_path)
    assert [p["id"] for p in catalog.all()] == ["horizontal-720p30"]
    with pytest.raises(RenderError) as caught:
        catalog.get("hevc")
    assert caught.value.code == "render.unknown_preset"
