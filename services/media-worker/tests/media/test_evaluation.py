# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.evaluation.capture import capture
from openworld_moments.evaluation.holdout import generate
from openworld_moments.evaluation.service import (
    EvaluationError,
    evaluate,
    markdown,
    read_document,
    write_report,
)
from openworld_moments.media.tools import MediaTools, ToolInfo


def test_real_holdout_capture_frozen_report_cli_and_privacy(
    tmp_path: Path, tools: MediaTools, ffmpeg: ToolInfo
) -> None:
    data = tmp_path / "private captures café"
    manifest = generate(data, tools)
    mapping = data / "media-map.private.json"
    observations = capture(manifest, mapping, tools)
    report = evaluate(manifest, observations)
    assert report["metrics"]["true_positives"] == 3
    assert report["metrics"]["false_positives"] == report["metrics"]["false_negatives"] == 0
    assert report["metrics"]["median_timestamp_error_ms"] == 0
    assert len(report["compatibility"]) == 2
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_report(report, first)
    write_report(evaluate(manifest, observations), second)
    assert (first / "report.json").read_bytes() == (second / "report.json").read_bytes()
    assert (first / "report.md").read_bytes() == (second / "report.md").read_bytes()
    assert str(tmp_path) not in (first / "report.json").read_text()
    assert "café" not in markdown(report) and "media-map" not in markdown(report)
    output = tmp_path / "observations.json"
    output.write_text(json.dumps(observations))
    cli = subprocess.run(  # noqa: S603 - fixed interpreter and generated test inputs
        [
            sys.executable,
            "-m",
            "openworld_moments.detectors",
            "eval",
            "run",
            str(data / "manifest.json"),
            "--observations",
            str(output),
            "--output",
            str(tmp_path / "cli"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    assert json.loads(cli.stdout) == report
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AnalysisCancelled):
        capture(manifest, mapping, tools, cancel=cancel)
    bad = copy.deepcopy(manifest)
    bad["clips"][0]["sha256"] = "f" * 64
    mapdoc = json.loads(mapping.read_text())
    mapdoc["f" * 64] = mapdoc.pop(manifest["clips"][0]["sha256"])
    badmap = tmp_path / "bad.json"
    badmap.write_text(json.dumps(mapdoc))
    with pytest.raises(EvaluationError, match="match its annotation hash"):
        capture(bad, badmap, tools)
    hostile = tmp_path / "hostile.json"
    hostile.write_text('{"schema_version":"1.14","path":"private"}')
    with pytest.raises(EvaluationError, match="invalid"):
        read_document(hostile, "evaluation")
