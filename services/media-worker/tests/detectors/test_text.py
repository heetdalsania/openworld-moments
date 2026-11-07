# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import threading
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from openworld_moments.detectors.ocr import Line, Reading, Tesseract, parse_tsv, preprocess
from openworld_moments.detectors.sdk import AnalysisCancelled, AnalysisContext, AnalysisError, Frame
from openworld_moments.detectors.text import (
    CATEGORIES,
    SubtitleDetector,
    TextDetector,
    TextIntervals,
    TextSample,
    classify,
)
from openworld_moments.detectors.text_fixtures import BANNER_REGION, SUBTITLE_REGION
from openworld_moments.media.process import ToolCancelled, ToolResult, ToolTimeout

VOCABULARY = {
    "failure": ("TRY AGAIN",),
    "arrest": ("CAUGHT",),
    "mission-started": ("TASK STARTED",),
    "mission-objective": ("NEW OBJECTIVE",),
    "mission-completed": ("TASK COMPLETE",),
    "mission-failed": ("TASK FAILED",),
}


class Backend:
    def __init__(self, readings: dict[int, Reading]) -> None:
        self.readings = readings
        self.calls = 0
        self.hash = "a" * 64

    def prepare(self, language: str, cancel: threading.Event) -> dict[str, str]:
        assert language == "eng"
        return {"ocr_engine": "fake-1", "ocr_model_sha256": self.hash, "ocr_language": language}

    def read(self, frame: Frame, mode: str, cancel: threading.Event) -> Reading:
        self.calls += 1
        return self.readings.get(frame.pixels[0], Reading())


def reading(text: str, score: float = 0.95, region: tuple[float, ...] = BANNER_REGION) -> Reading:
    return Reading((Line(text, region, score),)) if text else Reading()


def run(
    texts: list[str],
    *,
    subtitle: bool = False,
    scores: dict[str, float] | None = None,
    vocabulary: dict[str, tuple[str, ...]] | None = None,
    **settings: Any,
) -> tuple[list[Any], Backend]:
    region = SUBTITLE_REGION if subtitle else BANNER_REGION
    values = {text: i for i, text in enumerate(dict.fromkeys(texts))}
    backend = Backend(
        {i: reading(t, (scores or {}).get(t, 0.95), region) for t, i in values.items()}
    )
    detector = SubtitleDetector(backend) if subtitle else TextDetector(backend)
    context = AnalysisContext(
        "synthetic",
        len(texts) * 500,
        tuple(
            Frame(i * 500, 640, 128, bytes([values[t]]) * (640 * 128), region)
            for i, t in enumerate(texts)
        ),
        MappingProxyType({detector.sample_region: region}),
        MappingProxyType({"confirmation_frames": 2, **settings}),
        MappingProxyType(vocabulary or VOCABULARY),
        lambda: None,
        lambda *_: None,
    )
    detector.configure(
        context.settings, {"version": "1.0.0", "ocr_language": "eng"}, threading.Event()
    )
    detector.setup(context)
    try:
        return list(detector.detect(context)), backend
    finally:
        detector.close()


@pytest.mark.parametrize("category", list(CATEGORIES))
def test_exact_known_banners_have_constrained_categories(category: str) -> None:
    assert classify(VOCABULARY[category][0], VOCABULARY, 0.9) == (category, 1)


def test_fuzzy_match_is_whole_text_and_ambiguous_or_short_matches_are_unknown() -> None:
    assert classify("TASK C0MPLETE", VOCABULARY, 0.9)[0] == "mission-completed"
    assert classify("PLEASE DO NOT SAY TASK COMPLETE", VOCABULARY, 0.9)[0] is None
    assert classify("CAUGNT", VOCABULARY, 0.8)[0] is None
    assert classify("TASK COMPLETE", {**VOCABULARY, "failure": ("TASK COMPLETE",)}, 0.9)[0] is None
    assert classify("BLUE UMBRELLA", VOCABULARY, 0.9)[0] is None


def test_persistent_subtitle_one_interval_and_exact_visible_speaker() -> None:
    events, backend = run(["MORGAN: MEET AT BRIDGE"] * 6 + [""] * 2, subtitle=True)
    assert len(events) == 1 and backend.calls == 2
    event = events[0]
    assert (event.type, event.start_ms, event.end_ms) == ("openworld.subtitle", 0, 3000)
    assert event.attributes["speaker"] == "MORGAN"
    assert event.attributes["confirmed_at_ms"] == 500
    assert event.attributes["closed_by"] == "absence"
    with pytest.raises(TypeError):
        event.evidence[0]["lines"][0]["text"] = "mutated"


def test_text_changes_and_clip_end_close_each_confirmed_interval_once() -> None:
    events, _ = run(["FIRST LINE"] * 3 + ["SECOND LINE"] * 3, subtitle=True)
    assert [(e.start_ms, e.end_ms, e.attributes["closed_by"]) for e in events] == [
        (0, 1500, "text_changed"),
        (1500, 3000, "clip_end"),
    ]


def test_misses_flicker_and_reappearance() -> None:
    events, _ = run(["TASK COMPLETE", "", "TASK COMPLETE", "TASK COMPLETE", "", "TASK COMPLETE"])
    assert len(events) == 1 and events[0].evidence[1]["score"] < 1
    events, _ = run(["CAUGHT"] * 3 + [""] * 3 + ["CAUGHT"] * 3)
    assert len(events) == 2 and [e.start_ms for e in events] == [0, 3000]
    assert run(["CAUGHT", "", "TRY AGAIN", ""])[0] == []


def test_unknown_and_low_confidence_never_fabricate_mission_events() -> None:
    events, _ = run(["BLUE UMBRELLA"] * 3)
    assert len(events) == 1 and events[0].type == "openworld.ocr_text"
    assert events[0].confidence <= 0.49 and events[0].attributes["text"] == "BLUE UMBRELLA"
    assert "category" not in events[0].attributes
    assert run(["TASK COMPLETE"] * 3, scores={"TASK COMPLETE": 0.4})[0] == []
    events, _ = run(["TASK COMPLETE"] * 3)
    assert events[0].attributes["spoiler_risk"] is True


def test_cancellation_and_region_metadata_are_checked() -> None:
    backend = Backend({0: reading("CAUGHT")})
    detector = TextDetector(backend)
    detector.configure({}, {"version": "1.0.0", "ocr_language": "eng"}, threading.Event())

    def cancel() -> None:
        raise AnalysisCancelled

    context = AnalysisContext(
        "fixture",
        1000,
        (Frame(0, 640, 128, bytes(81920), BANNER_REGION),),
        MappingProxyType({"mission_banner": BANNER_REGION}),
        MappingProxyType({}),
        MappingProxyType(VOCABULARY),
        cancel,
        lambda *_: None,
    )
    with pytest.raises(AnalysisCancelled):
        list(detector.detect(context))
    with pytest.raises(AnalysisError, match="calibrated"):
        list(
            detector.detect(
                replace(
                    context,
                    frames=(replace(context.frames[0], region=None),),
                    check_cancelled=lambda: None,
                )
            )
        )


HEADER = (
    b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    b"left\ttop\twidth\theight\tconf\ttext\n"
)


def test_tsv_lines_use_global_coordinates_and_keep_multiline_text() -> None:
    frame = Frame(500, 640, 128, bytes(81920), BANNER_REGION)
    result = parse_tsv(
        HEADER + b"5\t1\t1\t1\t1\t1\t18\t18\t100\t20\t95\tHELLO\n"
        b"5\t1\t1\t1\t2\t1\t18\t48\t100\t20\t90\tWORLD\n",
        frame,
    )
    assert result.text == "HELLO\nWORLD" and result.score == 0.9
    assert result.lines[0].region == pytest.approx((0.1125, 0.21875, 0.125, 0.0375))


@pytest.mark.parametrize(
    "row",
    [
        b"5\t1\t1\t1\t1\t1\t-1\t18\t100\t20\t95\tTEXT\n",
        b"5\t1\t1\t1\t1\t1\t18\t18\t9999\t20\t95\tTEXT\n",
        b"5\t1\t1\t1\t1\t1\t18\t18\t100\t20\tnan\tTEXT\n",
        b"5\t1\t1\t1\t1\t1\t18\t18\t100\t20\t95\tTEXT\textra\n",
        b"5\t1\t1\t1\t1\t1\t18\t18\t100\t20\t95\t" + b"x" * 501 + b"\n",
    ],
)
def test_hostile_tsv_is_rejected(row: bytes) -> None:
    with pytest.raises(AnalysisError, match="TSV"):
        parse_tsv(HEADER + row, Frame(0, 640, 128, bytes(81920), BANNER_REGION))


def test_preprocessing_flat_invalid_and_contrast_variants() -> None:
    frame = Frame(0, 640, 128, bytes(81920), BANNER_REGION)
    assert preprocess(frame, "contrast") is None
    with pytest.raises(AnalysisError):
        preprocess(replace(frame, pixels=b""), "threshold")
    image = replace(frame, pixels=bytes([20, 120, 240, 20]) * 20480)
    gray = preprocess(image, "contrast")
    binary = preprocess(image, "threshold")
    assert gray and binary and gray != binary
    assert gray.startswith(b"P5\n656 144\n255\n")


def test_missing_ocr_and_hostile_language_degrade_without_running() -> None:
    with pytest.raises(AnalysisError, match="Install local"):
        Tesseract("/absent/tesseract").prepare("eng", threading.Event())
    with pytest.raises(AnalysisError, match="language ID"):
        Tesseract().prepare("../eng", threading.Event())
    with pytest.raises(AnalysisError, match="locale pack"):
        TextDetector().configure({}, {}, threading.Event())


def test_ocr_cancellation_failure_and_scratch_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    import openworld_moments.detectors.ocr as module

    backend = Tesseract()
    backend.executable = "trusted-test-tool"
    backend.language = "eng"
    frame = Frame(0, 640, 128, bytes([20, 240]) * 40960, BANNER_REGION)
    paths = []

    def fail(*args: Any, **kwargs: Any) -> ToolResult:
        paths.append(kwargs["cwd"])
        assert (Path(kwargs["cwd"]) / "input.pgm").is_file()
        raise ToolCancelled("cancelled")

    monkeypatch.setattr(module, "run_tool", fail)
    with pytest.raises(ToolCancelled):
        backend.read(frame, "contrast", threading.Event())
    assert paths and all(not p.exists() for p in paths)

    def timeout(*args: Any, **kwargs: Any) -> ToolResult:
        raise ToolTimeout("timeout")

    monkeypatch.setattr(module, "run_tool", timeout)
    with pytest.raises(ToolTimeout):
        backend.read(frame, "threshold", threading.Event())


@pytest.mark.parametrize("reported_version", ["5.5.4", "v5.5.3.20260724"])
def test_model_digest_and_mid_analysis_changes_fail_closed(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, reported_version: str
) -> None:
    import openworld_moments.detectors.ocr as module

    executable = tmp_path / "tesseract"
    executable.write_bytes(b"trusted tool placeholder")
    model = tmp_path / "eng.traineddata"
    model.write_bytes(b"synthetic model identity")

    def reply(argv: Any, **kwargs: Any) -> ToolResult:
        data = (
            f"tesseract {reported_version}\n".encode()
            if "--version" in argv
            else f'List of available languages in "{tmp_path}" (1):\neng\n'.encode()
        )
        return ToolResult(0, data, "")

    monkeypatch.setattr(module, "run_tool", reply)
    backend = Tesseract(str(executable))
    versions = backend.prepare("eng", threading.Event())
    assert versions["ocr_engine"] == "tesseract-" + reported_version.removeprefix("v")
    assert len(versions["ocr_model_sha256"]) == 64
    backend.verify_model(threading.Event())
    model.write_bytes(b"changed language model")
    with pytest.raises(AnalysisError, match="changed"):
        backend.verify_model(threading.Event())


@pytest.mark.parametrize("reported_version", ["4.1.1", "v4.1.1"])
def test_old_ocr_engine_is_rejected_with_or_without_version_prefix(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, reported_version: str
) -> None:
    import openworld_moments.detectors.ocr as module

    executable = tmp_path / "tesseract"
    executable.write_bytes(b"trusted tool placeholder")
    monkeypatch.setattr(
        module,
        "run_tool",
        lambda *args, **kwargs: ToolResult(0, f"tesseract {reported_version}\n".encode(), ""),
    )
    with pytest.raises(AnalysisError, match="unavailable"):
        Tesseract(str(executable)).prepare("eng", threading.Event())


def test_confirmed_banner_ocr_spelling_variants_do_not_split_the_same_phrase() -> None:
    events, _ = run(["TASK COMPLETE"] * 3 + ["TASK C0MPLETE"] * 3 + ["TASK COMPLETE"] * 3)
    assert len(events) == 1 and events[0].type == "openworld.mission_completed"
    assert events[0].start_ms == 0 and events[0].end_ms == 4500


def test_distinct_configured_phrases_keep_separate_intervals() -> None:
    events, _ = run(
        ["REACH LOCATION A"] * 3 + ["REACH LOCATION B"] * 3,
        vocabulary={**VOCABULARY, "mission-objective": ("REACH LOCATION A", "REACH LOCATION B")},
    )
    assert [(e.start_ms, e.end_ms) for e in events] == [(0, 1500), (1500, 3000)]
    assert [e.attributes["text"] for e in events] == ["REACH LOCATION A", "REACH LOCATION B"]


def test_sampling_gaps_reset_confirmation_and_reject_repeated_timestamps() -> None:
    state = TextIntervals(2, 1)
    sample = TextSample(reading("HELLO WORLD"), "openworld.subtitle", None, 1, 0.95, 0)
    assert state.observe(0, sample) == []
    assert state.observe(500, replace(sample, frame_ms=500)) == []
    closed = state.observe(2000, replace(sample, frame_ms=2000))
    assert len(closed) == 1 and closed[0][1] == "gap"
    assert (closed[0][0].first_ms, closed[0][0].last_ms) == (0, 500)
    assert state.active is None
    assert state.observe(2500, replace(sample, frame_ms=2500)) == []
    assert state.active is not None and state.active.first_ms == 2000
    with pytest.raises(AnalysisError, match="strictly ascend"):
        state.observe(2500, sample)


def test_undersized_proxy_text_region_is_refused() -> None:
    from openworld_moments.detectors.inputs import require_text_detail

    require_text_detail(1280, 720, BANNER_REGION)
    with pytest.raises(AnalysisError, match="too small"):
        require_text_detail(1280, 720, (0.1, 0.2, 0.01, 0.24))
    with pytest.raises(AnalysisError, match="too small"):
        require_text_detail(1280, 720, (0.1, 0.2, 0.8, 0.01))
