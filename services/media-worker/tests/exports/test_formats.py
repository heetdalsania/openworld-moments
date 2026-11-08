# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open-format exports: goldens, determinism, validation, round trips, privacy, warnings.

Goldens live in ``goldens/``; regenerate them deliberately with
``OWM_UPDATE_GOLDENS=1 uv run pytest tests/exports``.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import opentimelineio as otio
import pytest
from openworld_moments_contracts import load, normalize

from openworld_moments.exports.formats import CSV_COLUMNS, captions_text, parse_captions
from openworld_moments.exports.service import ExportFailed
from tests.exports.conftest import AST, AST2, DOCUMENT, GOLDENS, SHA2, Fixture

FORMATS = ("project", "events", "srt", "vtt", "csv", "otio", "fcpxml")
GOLDEN_NAMES = {
    "project": "project.owm.json",
    "events": "events.jsonl",
    "srt": "captions.srt",
    "vtt": "captions.vtt",
    "csv": "markers.csv",
    "otio": "timeline.otio",
    "fcpxml": "timeline.fcpxml",
}


def ms(time: otio.opentime.RationalTime) -> int:
    seconds: float = time.to_seconds()
    return round(seconds * 1000)


DESKTOP_FIXTURES = Path(__file__).resolve().parents[4] / "apps" / "desktop" / "src" / "testing"


@pytest.mark.parametrize("fmt", FORMATS)
def test_exports_match_goldens_and_are_byte_stable(project: Fixture, fmt: str) -> None:
    first = project.export(fmt)
    assert project.export(fmt) == first  # re-export of unchanged data
    load("export-result", first)
    golden = GOLDENS / GOLDEN_NAMES[fmt]
    if os.environ.get("OWM_UPDATE_GOLDENS") == "1":
        golden.parent.mkdir(exist_ok=True)
        golden.write_bytes(first["content"].encode("utf-8"))
    assert first["content"].encode("utf-8") == golden.read_bytes()
    assert first["stability"] == ("experimental" if fmt == "fcpxml" else "stable")
    assert first["includes_paths"] is False


def test_only_saved_changes_change_the_bytes(project: Fixture) -> None:
    before = {fmt: project.export(fmt)["sha256"] for fmt in FORMATS}
    # An unsaved recovery draft and an unrelated session leave every export unchanged.
    draft = copy.deepcopy(DOCUMENT)
    draft["project"]["title"] = "Unsaved draft"
    project.sql(
        "UPDATE editor_projects SET recovery_json = ? WHERE project_id = ?",
        (json.dumps(draft), DOCUMENT["project"]["id"]),
    )
    project.sql(
        "INSERT INTO sessions (id, title, review_state, created_at) VALUES "
        "('ses_01JCBQ00000000000000000077', 'Other', 'unreviewed', '2026-11-20T00:00:00Z')"
    )
    assert {fmt: project.export(fmt)["sha256"] for fmt in FORMATS} == before
    saved = copy.deepcopy(DOCUMENT)
    saved["project"]["title"] = "Renamed"
    project.save(saved, revision=4)
    after = {fmt: project.export(fmt)["sha256"] for fmt in FORMATS}
    assert after["project"] != before["project"] and after["otio"] != before["otio"]
    assert after["srt"] == before["srt"]  # captions did not change


def test_project_json_is_lossless_and_versioned(project: Fixture) -> None:
    result = project.export("project")
    doc = json.loads(result["content"])
    load("project-export", doc)
    assert doc["format"] == "openworld-moments.project" and doc["format_version"] == "1.0"
    assert doc["project_revision"] == 3 and doc["saved_at"] == "2026-11-21T11:00:00.000Z"
    saved = normalize(load("editor-project", copy.deepcopy(DOCUMENT)))
    assert doc["document"] == saved
    assert "source_locations" not in doc and doc["extensions"]["privacy_review"]["acknowledged"]
    # Forward compatibility: unknown additions live in extensions and still read.
    doc["extensions"] = {"org.example.future": {"x": 1}}
    load("project-export", doc)


def test_event_jsonl_lines_validate_and_place_events(project: Fixture) -> None:
    lines = project.export("events")["content"].splitlines()
    header, *records = (json.loads(line) for line in lines)
    for line in (header, *records):
        load("event-export", line)
    assert header["record"] == "header" and header["event_count"] == 4 == len(records)
    assert [r["observation"]["id"][-2:] for r in records] == ["32", "31", "34", "33"]
    by_id = {r["observation"]["id"][-2:]: r for r in records}
    assert by_id["31"]["effective"]["review_state"] == "confirmed"
    assert by_id["31"]["project_ranges"] == [{"start_ms": 7500, "end_ms": 9500}]
    assert by_id["33"]["effective"] == {
        "type": "openworld.busted",
        "start_ms": 52500,
        "end_ms": 53500,
        "review_state": "corrected",
        "revision": 1,
    }
    assert by_id["33"]["observation"]["start_ms"] == 52000  # original kept
    assert by_id["33"]["project_ranges"] == [{"start_ms": 34800, "end_ms": 35800}]
    assert by_id["32"]["project_ranges"] == []  # outside the project
    assert by_id["34"]["effective"]["review_state"] == "rejected"  # kept in JSONL
    assert all(r["status"] == "current" for r in records)


def test_captions_round_trip_and_match_the_desktop_serializer(project: Fixture) -> None:
    cues = DOCUMENT["project"]["captions"]
    for fmt in ("srt", "vtt"):
        text = project.export(fmt)["content"]
        back = parse_captions(text, fmt)
        assert back == cues
        # Caption timing equals the project timeline exactly (well within one frame).
        assert [(c["start_ms"], c["end_ms"]) for c in back] == [
            (c["start_ms"], c["end_ms"]) for c in cues
        ]
        # The desktop's shared fixtures re-serialize byte-for-byte (same rules in TS).
        desktop = (DESKTOP_FIXTURES / f"captions.{fmt}").read_text("utf-8")
        assert captions_text(parse_captions(desktop, fmt), fmt) == desktop


def test_csv_markers_parse_back_and_neutralize_formulas(project: Fixture) -> None:
    result = project.export("csv")
    rows = list(csv.DictReader(io.StringIO(result["content"], newline="")))
    assert tuple(rows[0]) == CSV_COLUMNS
    kinds = [r["kind"] for r in rows]
    assert kinds.count("cut") == 2 and kinds.count("event") == 2 and kinds.count("caption") == 2
    formula = next(r for r in rows if r["label"].startswith("'"))
    assert formula["label"] == "'=SUM(A1) 你好 second line"
    assert all(int(r["end_ms"]) - int(r["start_ms"]) == int(r["duration_ms"]) for r in rows)
    starts = [int(r["start_ms"]) for r in rows]
    assert starts == sorted(starts)
    assert "\r\n" in result["content"]


def test_otio_opens_in_the_reference_library(project: Fixture) -> None:
    result = project.export("otio")
    timeline = otio.adapters.read_from_string(result["content"], "otio_json")
    assert isinstance(timeline, otio.schema.Timeline)
    video, audio = timeline.tracks
    assert video.kind == otio.schema.TrackKind.Video and audio.kind == otio.schema.TrackKind.Audio
    clips = list(video.find_clips())
    assert [ms(c.source_range.start_time) for c in clips] == [12500, 50000]
    assert ms(video.duration()) == 43300
    assert [c.media_reference.target_url for c in clips] == [
        "Capture%2001%20%E2%80%94%20Caf%C3%A9.mp4"
    ] * 2
    markers = sorted((ms(m.marked_range.start_time), m.name) for m in video.markers)
    assert markers == [
        (1000, "Here we go & <go> → 🚗"),
        (3000, "=SUM(A1) 你好\nsecond line"),
        (7500, "openworld.wanted_level_changed"),
        (34800, "openworld.busted"),
    ]
    meta = clips[0].metadata["openworld_moments"]
    assert meta["crop"]["mode"] == "safe" and "vertical_crop" in meta  # kept, not lost
    assert timeline.metadata["openworld_moments"]["overlays"][0]["kind"] == "blur"
    # The library writes it back without loss of the parts it understands.
    again = otio.adapters.read_from_string(
        otio.adapters.write_to_string(timeline, "otio_json"), "otio_json"
    )
    assert again.duration() == timeline.duration()


def test_fcpxml_is_well_formed_and_labelled_experimental(project: Fixture) -> None:
    result = project.export("fcpxml")
    assert result["stability"] == "experimental" and result["format_version"].endswith(
        "experimental"
    )
    content = result["content"]
    assert content.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n')
    root = ET.fromstring(content.split("\n", 2)[2])  # noqa: S314 - our own output
    assert root.tag == "fcpxml" and root.get("version") == "1.10"
    clips = root.findall("./library/event/project/sequence/spine/asset-clip")
    assert [(c.get("offset"), c.get("start"), c.get("duration")) for c in clips] == [
        ("0s", "12500/1000s", "32300/1000s"),
        ("32300/1000s", "50000/1000s", "11000/1000s"),
    ]
    project_el = root.find("./library/event/project")
    assert project_el is not None and project_el.get("name") == 'Six-star escape: "Café" run'
    values = [m.get("value") for c in clips for m in c.findall("marker")]
    assert "openworld.busted" in values and any(v and v.startswith("Caption: ") for v in values)


def test_no_absolute_paths_unless_explicitly_requested(project: Fixture, tmp_path: Path) -> None:
    for fmt in FORMATS:
        content = project.export(fmt)["content"]
        assert str(tmp_path) not in content and "file:" not in content, fmt
    for fmt in ("events", "srt", "vtt", "csv"):
        with pytest.raises(ExportFailed) as refused:
            project.export(fmt, include_paths=True)
        assert refused.value.code == "export.paths_not_supported"
    with_paths = project.export("project", include_paths=True)
    doc = json.loads(with_paths["content"])
    assert with_paths["includes_paths"] is True and "source_paths" in doc["capabilities"]
    assert [loc["asset_id"] for loc in doc["source_locations"]] == [AST]
    assert doc["source_locations"][0]["path"].startswith("file:")
    for fmt in ("otio", "fcpxml"):
        result = project.export(fmt, include_paths=True)
        assert result["includes_paths"] is True and "file:" in result["content"]


def _with_missing_source(project: Fixture) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["sources"].append(
        {
            "asset_id": AST2,
            "sha256": SHA2,
            "original_name": "Phone clip.mov",
            "duration_ms": 30000,
            "requires_relink": True,
        }
    )
    document["project"]["tracks"][0]["segments"].append(
        {
            "id": "seg_01JCBQ00000000000000000008",
            "asset_id": AST2,
            "source_in_ms": 0,
            "source_out_ms": 2000,
            "timeline_start_ms": 43300,
            "crop": {"mode": "fit", "keyframes": []},
        }
    )
    project.save(document, revision=5)


def test_missing_sources_warn_and_are_referenced_by_hash(project: Fixture) -> None:
    _with_missing_source(project)
    for fmt in ("project", "csv", "otio", "fcpxml"):
        codes = {
            w["code"]: w
            for w in project.export(
                fmt, **({} if fmt == "csv" else {"include_paths": fmt != "csv"})
            )["warnings"]
        }
        assert codes["export.source_missing"]["count"] == 1, fmt
    timeline = otio.adapters.read_from_string(project.export("otio")["content"], "otio_json")
    last = list(timeline.tracks[0].find_clips())[-1]
    assert isinstance(last.media_reference, otio.schema.MissingReference)
    assert last.metadata["openworld_moments"]["sha256"] == SHA2
    doc = json.loads(project.export("project", include_paths=True)["content"])
    assert [loc["asset_id"] for loc in doc["source_locations"]] == [AST]
    fcp = project.export("fcpxml")["content"]
    root = ET.fromstring(fcp.split("\n", 2)[2])  # noqa: S314 - our own output
    assets = {a.get("name"): a for a in root.findall("./resources/asset")}
    assert assets["Phone clip.mov"].find("media-rep") is None


def test_unsupported_operations_warn_instead_of_dropping(project: Fixture) -> None:
    codes = {w["code"]: w["count"] for w in project.export("otio")["warnings"]}
    assert codes == {
        "export.audio_gain_not_supported": 2,
        "export.audio_mute_not_supported": 1,
        "export.blur_not_supported": 1,
        "export.captions_as_markers": 2,
        "export.crop_not_supported": 1,
        "export.text_overlay_not_supported": 1,
        "export.vertical_crop_not_supported": 1,
    }
    plain = copy.deepcopy(DOCUMENT)
    plain["project"]["captions"] = []
    plain["project"]["overlays"] = []
    plain["project"]["audio"] = {"gain_db": 0, "mute_ranges": []}
    for seg in plain["project"]["tracks"][0]["segments"]:
        seg["crop"] = {"mode": "fit", "keyframes": []}
        seg.pop("vertical_crop", None)
    project.save(plain, revision=6)
    for fmt in FORMATS:
        warnings = project.export(fmt)["warnings"]
        assert [w["code"] for w in warnings] == (
            ["export.no_captions"] if fmt in ("srt", "vtt") else []
        ), fmt


def test_caption_style_and_invalid_captions(project: Fixture) -> None:
    styled = copy.deepcopy(DOCUMENT)
    styled["project"]["caption_settings"] = {
        "preset": "compact",
        "region": [0.1, 0.8, 0.8, 0.1],
        "burn_in": True,
        "sidecar": "srt",
    }
    project.save(styled, revision=7)
    assert [w["code"] for w in project.export("vtt")["warnings"]] == [
        "export.caption_style_not_supported"
    ]
    broken: dict[str, Any] = copy.deepcopy(DOCUMENT)
    broken["project"]["captions"] = [{"start_ms": 0, "end_ms": 500, "text": "line\n\nblank"}]
    project.save(broken, revision=8)
    with pytest.raises(ExportFailed) as caught:
        project.export("srt")
    assert caught.value.code == "export.captions_invalid"


def test_unknown_project_and_format(project: Fixture) -> None:
    with pytest.raises(ExportFailed) as missing:
        project.exporter.project("prj_01JCBQ00000000000000000099", "project")
    assert missing.value.status == 404
    with pytest.raises(ExportFailed):
        project.exporter.project(DOCUMENT["project"]["id"], "edl")
