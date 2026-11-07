# SPDX-License-Identifier: AGPL-3.0-or-later
"""whisper.cpp output parsing, word timing, session-time mapping and the explicit
model manager (M18). No engine or model is needed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from openworld_moments.transcripts.models import CATALOG, SpeechModels
from openworld_moments.transcripts.service import map_to_session
from openworld_moments.transcripts.whisper import (
    Recognition,
    Segment,
    TranscriptionError,
    Word,
    locate,
    parse_output,
    probe_engine,
)

FIXTURE = Path(__file__).with_name("whisper-full.json")
FAKE = Path(__file__).with_name("fake_whisper.py")


def fixture() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(FIXTURE.read_text("utf-8"))
    return doc


def test_full_json_becomes_timed_words() -> None:
    recognition = parse_output(FIXTURE.read_bytes(), 10_000)
    assert recognition.language == "en"
    first, second = recognition.segments
    assert (first.text, first.start_ms, first.end_ms) == ("Meet me at the bridge.", 0, 2000)
    assert [(w.text, w.start_ms, w.end_ms, w.confidence) for w in first.words] == [
        ("Meet", 0, 300, 0.95),
        ("me", 300, 450, 0.93),
        ("at", 450, 600, 0.9),
        ("the", 600, 750, 0.88),
        # sub-word tokens join; the word's confidence is its weakest token's
        ("bridge.", 750, 1400, 0.8),
    ]
    assert [(w.text, w.start_ms, w.end_ms) for w in second.words] == [
        ("Go,", 2500, 2850),
        ("go!", 2900, 3400),
    ]
    assert first.confidence == pytest.approx((0.95 + 0.93 + 0.9 + 0.88 + 0.8) / 5, abs=1e-4)


def test_times_are_clamped_into_the_clip_and_monotonic() -> None:
    doc = fixture()
    doc["transcription"][1]["offsets"] = {"from": 1500, "to": 9000}  # starts before seg 1 ends
    recognition = parse_output(json.dumps(doc).encode(), 3000)
    second = recognition.segments[1]
    assert second.start_ms == 2000 and second.end_ms == 3000
    assert all(2000 <= w.start_ms <= w.end_ms <= 3000 for w in second.words)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("transcription"),
        lambda d: d["transcription"][0].update(offsets={"from": "zero", "to": 1}),
        lambda d: d["transcription"][0]["tokens"][1].update(p=True),
        lambda d: d["transcription"][0].update(text="bell\x07"),
        lambda d: d.update(transcription=[{} for _ in range(20_001)]),
    ],
)
def test_invalid_output_is_rejected_without_leaking_text(mutate) -> None:  # type: ignore[no-untyped-def]
    doc = fixture()
    mutate(doc)
    with pytest.raises(TranscriptionError) as caught:
        parse_output(json.dumps(doc).encode(), 10_000)
    assert caught.value.code == "transcription.invalid_output"
    assert "bridge" not in caught.value.message.lower()


def test_non_json_and_non_finite_numbers_are_rejected() -> None:
    for data in (b"{not json", b'{"transcription": [], "x": NaN}', b"\xff\xfe"):
        with pytest.raises(TranscriptionError):
            parse_output(data, 1000)


def test_unknown_language_codes_are_dropped() -> None:
    doc = fixture()
    doc["result"]["language"] = "../en"
    assert parse_output(json.dumps(doc).encode(), 10_000).language is None


def test_mapping_drops_speech_inside_hidden_repeated_footage() -> None:
    words = (Word("one", 0, 400, 0.9), Word("two", 500, 1100, 0.8), Word("three", 1200, 1500, 0.7))
    recognition = Recognition(
        "en",
        (
            Segment("early", 0, 300, (Word("early", 0, 300, 0.9),)),
            Segment("one two three", 0, 1500, words),
            Segment("later", 2000, 2400, (Word("later", 2000, 2400, 0.9),)),
        ),
    )
    # The first 1000 ms of this clip repeat the previous clip; the clip starts at 60 s.
    rows = map_to_session(recognition, hidden_ms=1000, virtual_start_ms=60_000)
    assert [r["text"] for r in rows] == ["two three", "later"]
    crossing = rows[0]
    assert (crossing["source_start_ms"], crossing["start_ms"]) == (1000, 60_000)
    assert [(w["text"], w["start_ms"], w["end_ms"]) for w in crossing["words"]] == [
        ("two", 60_000, 60_100),
        ("three", 60_200, 60_500),
    ]
    assert rows[1]["start_ms"] == 61_000 and rows[1]["source_start_ms"] == 2000
    assert crossing["confidence"] == pytest.approx(0.75)


def test_mapping_without_overlap_keeps_source_times_offset() -> None:
    recognition = parse_output(FIXTURE.read_bytes(), 10_000)
    rows = map_to_session(recognition, hidden_ms=0, virtual_start_ms=5000)
    assert [(r["start_ms"], r["end_ms"]) for r in rows] == [(5000, 7000), (7500, 9100)]
    assert rows[0]["words"][4]["source_start_ms"] == 750


def test_probe_records_version_and_digest() -> None:
    engine = probe_engine(FAKE, command=(sys.executable, str(FAKE)))
    assert engine.version == "1.7.6" and len(engine.sha256) == 64


def test_locate_prefers_the_explicit_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OWM_WHISPER", str(tmp_path / "missing"))
    assert locate() is None
    monkeypatch.setenv("OWM_WHISPER", str(FAKE))
    assert locate() == FAKE


def model_file(path: Path, magic: bytes = b"lmgg", size: int = 4096) -> Path:
    path.write_bytes(magic + b"\0" * (size - len(magic)))
    return path


def test_models_install_list_remove(tmp_path: Path) -> None:
    models = SpeechModels(tmp_path / "library")
    assert models.installed() == []
    installed = models.install(model_file(tmp_path / "downloaded.bin"), "base.en", "MIT")
    assert installed.public()["name"] == "base.en" and installed.size_bytes == 4096
    assert [m.name for m in models.installed()] == ["base.en"]
    assert models.get("base.en").sha256 == installed.sha256
    # The user's file is copied, never moved or modified.
    assert (tmp_path / "downloaded.bin").exists()
    models.remove("base.en")
    assert models.installed() == []
    with pytest.raises(TranscriptionError, match="not installed"):
        models.get("base.en")


@pytest.mark.parametrize(
    ("name", "license_id", "magic", "size", "message"),
    [
        ("../escape", "MIT", b"lmgg", 4096, "Model names"),
        ("Base", "MIT", b"lmgg", 4096, "Model names"),
        ("base.en", " ", b"lmgg", 4096, "license"),
        ("base.en", "MIT", b"PK\x03\x04", 4096, "ggml"),
        ("base.en", "MIT", b"lmgg", 100, "ggml"),
    ],
)
def test_model_install_validation(  # type: ignore[no-untyped-def]
    tmp_path: Path, name, license_id, magic, size, message
) -> None:
    models = SpeechModels(tmp_path / "library")
    with pytest.raises(TranscriptionError, match=message):
        models.install(model_file(tmp_path / "m.bin", magic, size), name, license_id)
    assert models.installed() == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_model_install_refuses_symlinks(tmp_path: Path) -> None:
    target = model_file(tmp_path / "real.bin")
    link = tmp_path / "link.bin"
    os.symlink(target, link)
    with pytest.raises(TranscriptionError):
        SpeechModels(tmp_path / "library").install(link, "base.en", "MIT")


def test_tampered_or_orphaned_sidecars_are_ignored(tmp_path: Path) -> None:
    models = SpeechModels(tmp_path / "library")
    models.install(model_file(tmp_path / "m.bin"), "tiny.en", "MIT")
    sidecar = models.directory / "tiny.en.json"
    doc = json.loads(sidecar.read_text("utf-8"))
    sidecar.write_text(json.dumps({**doc, "name": "../../etc"}), "utf-8")
    assert models.installed() == []
    sidecar.write_text(json.dumps(doc), "utf-8")
    (models.directory / "ggml-tiny.en.bin").write_bytes(b"lmgg")  # resized behind our back
    assert models.installed() == []


def test_catalog_lists_manual_sources_only() -> None:
    assert {m["name"] for m in CATALOG} >= {"tiny.en", "base.en", "small", "medium.en"}
    assert all(m["source_url"].startswith("https://") and m["license"] == "MIT" for m in CATALOG)
