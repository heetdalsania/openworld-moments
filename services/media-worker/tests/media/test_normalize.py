# SPDX-License-Identifier: AGPL-3.0-or-later
"""Normalization of FFprobe JSON, including metadata the synthetic fixtures cannot produce."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.media.probe import (
    AVERROR_INVALIDDATA,
    ProbeError,
    classify_failure,
    normalize,
)

BASE: dict[str, Any] = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 3840,
            "height": 2160,
            "pix_fmt": "yuv420p10le",
            "r_frame_rate": "60000/1001",
            "avg_frame_rate": "60000/1001",
            "color_range": "tv",
            "color_space": "bt2020nc",
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020",
            "duration": "30.030000",
            "tags": {"title": "My private title", "handler_name": "VideoHandler"},
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "channel_layout": "stereo",
            "sample_rate": "48000",
        },
    ],
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration": "30.030000",
        "bit_rate": "49990000",
        "tags": {"creation_time": "2026-11-20T10:14:22.000000Z", "location": "+40.1-074.0/"},
    },
}


def _norm(data: dict[str, Any]) -> dict[str, Any]:
    return normalize(data, size_bytes=1234, ffprobe_version="7.1.1")


def _with(**video: Any) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    data["streams"][0].update(video)
    return data


def test_xbox_style_hdr_capture() -> None:
    probe = _norm(BASE)
    assert probe["container"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert probe["duration_ms"] == 30030
    assert probe["bit_rate"] == 49990000
    assert probe["creation_time"] == "2026-11-20T10:14:22.000Z"
    video = probe["video"]
    assert video["frame_rate"] == {"num": 60000, "den": 1001}
    assert video["variable_frame_rate"] is False
    assert video["color"] == {
        "primaries": "bt2020",
        "transfer": "smpte2084",
        "matrix": "bt2020nc",
        "range": "tv",
        "hdr": True,
    }
    assert probe["audio"] == [
        {"codec": "aac", "channels": 2, "sample_rate_hz": 48000, "channel_layout": "stereo"}
    ]


def test_free_form_tags_and_location_are_dropped() -> None:
    text = repr(_norm(BASE))
    assert "My private title" not in text and "+40.1" not in text


def test_hdr_side_data_is_retained() -> None:
    side = [
        {
            "side_data_type": "Mastering display metadata",
            "red_x": "34000/50000",
            "min_luminance": "50/10000",
            "max_luminance": "10000000/10000",
        },
        {"side_data_type": "Content light level metadata", "max_content": 1000, "max_average": 400},
        {"side_data_type": "DOVI configuration record", "dv_profile": 8, "dv_level": 6},
    ]
    color = _norm(_with(side_data_list=side))["video"]["color"]
    assert color["mastering_display"] == {"min_luminance_nits": 0.005, "max_luminance_nits": 1000.0}
    assert color["content_light_level"] == {"max_cll": 1000, "max_fall": 400}
    assert color["dolby_vision"] == {"profile": 8, "level": 6}


def test_hlg_and_dolby_vision_count_as_hdr() -> None:
    assert _norm(_with(color_transfer="arib-std-b67"))["video"]["color"]["hdr"] is True
    sdr_dv = _with(
        color_transfer="bt709",
        side_data_list=[{"side_data_type": "DOVI configuration record", "dv_profile": 5}],
    )
    assert _norm(sdr_dv)["video"]["color"]["hdr"] is True
    assert _norm(_with(color_transfer="bt709"))["video"]["color"]["hdr"] is False


def test_unknown_color_values_are_omitted() -> None:
    color = _norm(
        _with(color_transfer="unknown", color_primaries="unspecified", color_space="reserved")
    )["video"]["color"]
    assert color == {"range": "tv", "hdr": False}


@pytest.mark.parametrize(
    ("video", "rotation"),
    [
        ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}, 90),
        ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": 90}]}, 270),
        ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": 180}]}, 180),
        ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": -89.9}]}, 90),
        ({"tags": {"rotate": "90"}}, 90),  # legacy clockwise tag
        ({}, 0),
    ],
)
def test_rotation_is_clockwise(video: dict[str, Any], rotation: int) -> None:
    assert _norm(_with(**video))["video"]["rotation"] == rotation


@pytest.mark.parametrize(
    ("r", "avg", "nominal", "variable"),
    [
        ("30000/1001", "30000/1001", (30000, 1001), False),
        ("60/1", "1200/29", (1200, 29), True),
        ("30/1", "2990/100", (299, 10), True),
        ("30/1", "2997/100", (30, 1), False),  # exactly 0.1% apart: the boundary is CFR
        ("30000/1001", "0/0", (30000, 1001), False),
        ("0/0", "24000/1001", (24000, 1001), False),
        ("60/1", "59997/1000", (60, 1), False),  # within 0.1%: still CFR
    ],
)
def test_frame_rates_stay_rational(
    r: str, avg: str, nominal: tuple[int, int], variable: bool
) -> None:
    video = _norm(_with(r_frame_rate=r, avg_frame_rate=avg))["video"]
    assert video["frame_rate"] == {"num": nominal[0], "den": nominal[1]}
    assert video["variable_frame_rate"] is variable


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (_with(r_frame_rate="0/0", avg_frame_rate="0/0"), "media.invalid_frame_rate"),
        (_with(codec_name="none"), "media.unsupported_codec"),
        (_with(width=0), "media.invalid_dimensions"),
        (_with(width=20000), "media.invalid_dimensions"),
    ],
)
def test_bad_video_streams(data: dict[str, Any], code: str) -> None:
    with pytest.raises(ProbeError) as caught:
        _norm(data)
    assert caught.value.code == code


def test_missing_duration() -> None:
    data = copy.deepcopy(BASE)
    del data["format"]["duration"]
    data["streams"][0]["duration"] = "N/A"
    with pytest.raises(ProbeError) as caught:
        _norm(data)
    assert caught.value.code == "media.invalid_duration"


def test_stream_duration_is_a_fallback() -> None:
    data = copy.deepcopy(BASE)
    del data["format"]["duration"]
    assert _norm(data)["duration_ms"] == 30030


def test_cover_art_only_is_no_video() -> None:
    data = copy.deepcopy(BASE)
    data["streams"][0]["disposition"] = {"attached_pic": 1}
    with pytest.raises(ProbeError) as caught:
        _norm(data)
    assert caught.value.code == "media.no_video_stream"
    assert caught.value.details["audio_only"] is True


def test_still_image_formats() -> None:
    data = copy.deepcopy(BASE)
    data["format"]["format_name"] = "png_pipe"
    with pytest.raises(ProbeError) as caught:
        _norm(data)
    assert caught.value.code == "media.still_image"


def test_unusable_audio_and_extra_streams_are_counted() -> None:
    data = copy.deepcopy(BASE)
    data["streams"] += [
        {"codec_type": "audio", "codec_name": "aac", "channels": 0, "sample_rate": "48000"},
        {"codec_type": "subtitle", "codec_name": "mov_text"},
        {"codec_type": "data", "codec_name": "bin_data"},
    ]
    probe = _norm(data)
    assert len(probe["audio"]) == 1
    assert probe["other_streams"] == 3


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-20T10:14:22.123456Z", "2026-11-20T10:14:22.123Z"),
        ("2026-11-20T03:14:22-07:00", "2026-11-20T10:14:22.000Z"),
        ("2026-11-20 10:14:22", "2026-11-20T10:14:22.000Z"),
        ("1904-01-01T00:00:00Z", None),  # QuickTime zero epoch
        ("1970-01-01T00:00:00Z", None),
        ("not a date", None),
    ],
)
def test_creation_time(value: str, expected: str | None) -> None:
    data = copy.deepcopy(BASE)
    data["format"]["tags"]["creation_time"] = value
    assert _norm(data).get("creation_time") == expected


def test_missing_container_is_unsupported() -> None:
    data = copy.deepcopy(BASE)
    data["format"] = {}
    with pytest.raises(ProbeError) as caught:
        _norm(data)
    assert caught.value.code == "media.unsupported_format"


@pytest.mark.parametrize(
    ("name", "stderr", "code"),
    [
        ("clip.mp4", "[mov @ 0x1] moov atom not found\n", "media.damaged"),
        ("clip.mkv", "EBML header parsing failed\n", "media.damaged"),
        ("clip.mp4", "Invalid data found when processing input\n", "media.damaged"),
        ("notes.txt", "Invalid data found when processing input\n", "media.unsupported_format"),
        ("clip.mp4", "Something unexpected\n", "media.probe_failed"),
    ],
)
def test_failure_classification(name: str, stderr: str, code: str) -> None:
    error = {"code": AVERROR_INVALIDDATA} if "Invalid data" in stderr else {"code": -5}
    failure = classify_failure(Path("/x") / name, error, stderr)
    assert failure.code == code
    assert failure.retryable is False
