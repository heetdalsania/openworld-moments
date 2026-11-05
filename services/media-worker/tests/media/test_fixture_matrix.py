# SPDX-License-Identifier: AGPL-3.0-or-later
"""Probe every generated fixture and check the normalized result (M04 fixture matrix)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from openworld_moments_contracts.generated.media_asset_schema import MediaProbe

from openworld_moments.media.fixtures import FIXTURES, Fixture
from openworld_moments.media.probe import ProbeError, probe_file
from openworld_moments.media.tools import ToolInfo


def _digest(path: Path) -> tuple[str, int, int]:
    info = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), info.st_size, info.st_mtime_ns


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_fixture_matrix(media_dir: Path, ffprobe: ToolInfo, fixture: Fixture) -> None:
    manifest = json.loads((media_dir / "manifest.json").read_text("utf-8"))
    name = fixture.name
    if name in manifest["skipped"]:
        pytest.skip(f"{name}: {manifest['skipped'][name]}")  # HEVC only when libx265 exists
    expect: dict[str, object] = manifest["generated"][name]
    path = media_dir / name
    before = _digest(path)

    if "error" in expect:
        with pytest.raises(ProbeError) as caught:
            probe_file(path, ffprobe)
        assert caught.value.code == expect["error"]
        assert str(path) not in caught.value.message
        assert str(path) not in caught.value.stderr_tail
    else:
        probe = probe_file(path, ffprobe)
        MediaProbe.model_validate(probe)  # contract-valid
        video = probe["video"]
        assert video["codec"] == expect["video_codec"]
        assert 800 <= probe["duration_ms"] <= 1200  # ~1 s; containers round differently
        assert probe["size_bytes"] == path.stat().st_size
        assert probe["probed_with"]["ffprobe_version"] == ffprobe.version
        assert (video["width"], video["height"]) == (320, 180)
        for rational in (video["frame_rate"], video["average_frame_rate"]):
            assert isinstance(rational["num"], int) and isinstance(rational["den"], int)
        if "audio" in expect:
            assert len(probe["audio"]) == expect["audio"]
            for audio in probe["audio"]:
                assert audio == {**audio, "codec": "aac", "channels": 2, "sample_rate_hz": 48000}
        if "frame_rate" in expect:
            rate = expect["frame_rate"]
            assert isinstance(rate, list)
            assert video["frame_rate"] == {"num": rate[0], "den": rate[1]}  # exact, not 29.97
        assert video["variable_frame_rate"] is expect.get("variable_frame_rate", False)
        assert video["rotation"] == expect.get("rotation", 0)
        assert video["color"]["hdr"] is expect.get("hdr", False)
        if "transfer" in expect:
            color = video["color"]
            assert color["transfer"] == expect["transfer"]
            assert color["primaries"] == "bt2020" and color["matrix"] == "bt2020nc"
        # The result never carries the path or the file name.
        assert name not in json.dumps(probe)

    assert _digest(path) == before, "probing changed the source bytes or modification time"


def test_vfr_fixture_keeps_exact_rationals(media_dir: Path, ffprobe: ToolInfo) -> None:
    video = probe_file(media_dir / "vfr.mp4", ffprobe)["video"]
    assert video["variable_frame_rate"] is True
    # The nominal rate of a VFR stream is its exact average, never a rounded float.
    assert video["frame_rate"] == video["average_frame_rate"]
    assert video["frame_rate"]["den"] > 1
