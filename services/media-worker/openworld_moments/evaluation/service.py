# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frozen inputs → deterministic JSON/Markdown. Reports whitelist only metric data."""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.errors import ContractError

from openworld_moments.detectors.profiles import canonical, digest
from openworld_moments.detectors.sdk import checkpoint
from openworld_moments.evaluation.metrics import measure
from openworld_moments.storage.repositories import SCHEMA_VERSION

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


class EvaluationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def read_document(path: Path, contract: str) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError("size")
        return normalize(load(contract, json.loads(raw)))
    except (OSError, ValueError, RecursionError, ContractError) as exc:
        raise EvaluationError(
            "evaluation.invalid_input", "Evaluation input is missing, oversized or invalid."
        ) from exc


def evaluate(
    manifest: dict[str, Any], observations: dict[str, Any], cancel: threading.Event | None = None
) -> dict[str, Any]:
    # Validate public calls too, not just the CLI. Never echo rejected input.
    try:
        manifest = normalize(load("evaluation", manifest))
        observations = normalize(load("evaluation-observations", observations))
    except ContractError as exc:
        raise EvaluationError("evaluation.invalid_input", "Evaluation input is invalid.") from exc
    if (
        observations["manifest_sha256"] != digest(manifest)
        or observations["profile"] != manifest["profile"]
    ):
        raise EvaluationError(
            "evaluation.input_mismatch",
            "Observations do not match this manifest and profile version.",
        )
    expected_ids = {c["sha256"] for c in manifest["clips"]}
    by_hash = {c["sha256"]: c for c in observations["clips"]}
    if set(by_hash) != expected_ids:
        raise EvaluationError(
            "evaluation.incomplete",
            "Every manifest clip needs exactly one observation record, including negative clips.",
        )

    def check() -> None:
        if cancel is not None:
            checkpoint(cancel)

    combined = []
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for clip in sorted(manifest["clips"], key=lambda c: c["sha256"]):
        check()
        observed = by_hash[clip["sha256"]]
        if any(e["end_ms"] > clip["duration_ms"] for e in observed["events"]):
            raise EvaluationError(
                "evaluation.invalid_interval", "A predicted event lies outside its annotated clip."
            )
        item = {**clip, "events": observed["events"], "processing_ms": observed["processing_ms"]}
        combined.append(item)
        grouped[
            tuple(clip[k] for k in ("width", "height", "locale", "hud_scale", "compression"))
        ].append(item)
    tolerance = manifest["tolerance_ms"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "owm-eval-1",
        "manifest_sha256": digest(manifest),
        "observations_sha256": digest(observations),
        "dataset_id": manifest["dataset_id"],
        "split": "holdout",
        "provenance": manifest["provenance"],
        "profile": manifest["profile"],
        "detectors": observations["detectors"],
        "tolerance_ms": tolerance,
        "metrics": measure(combined, tolerance, check),
        "clips": [
            {"sha256": c["sha256"], "metrics": measure([c], tolerance, check)} for c in combined
        ],
        "compatibility": [
            {
                **dict(
                    zip(("width", "height", "locale", "hud_scale", "compression"), key, strict=True)
                ),
                "metrics": measure(clips, tolerance, check),
                "status": "synthetic-only"
                if manifest["provenance"] == "synthetic"
                else "unvalidated",
            }
            for key, clips in sorted(grouped.items())
        ],
    }
    return normalize(load("evaluation-report", report))


def markdown(report: dict[str, Any]) -> str:
    report = normalize(load("evaluation-report", report))

    def value(n: Any) -> str:
        return (
            "Not defined"
            if n is None
            else f"{n:.6f}".rstrip("0").rstrip(".")
            if isinstance(n, float)
            else str(n)
        )

    m = report["metrics"]
    lines = [
        "# Local detector evaluation",
        "",
        f"Dataset: `{report['dataset_id']}` (holdout, {report['provenance']}).",
        f"Profile: `{report['profile']['id']}` {report['profile']['version']}.",
        f"Boundary tolerance: {report['tolerance_ms']} ms, inclusive at both ends.",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {value(v)} |" for k, v in m.items()]
    lines += [
        "",
        "## Compatibility matrix",
        "",
        "| Resolution | Locale | HUD scale | Compression | "
        "Precision | Recall | Footage hours | Status |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for row in report["compatibility"]:
        metrics = row["metrics"]
        lines.append(
            f"| {row['width']}x{row['height']} | {row['locale']} | "
            f"{value(row['hud_scale'])} | {row['compression']} | "
            f"{value(metrics['precision'])} | {value(metrics['recall'])} | "
            f"{value(metrics['duration_ms'] / 3_600_000)} | {row['status']} |"
        )
    lines += [
        "",
        "Synthetic results do not establish gameplay compatibility. "
        "Local evaluation never automatically validates a profile.",
        "Performance uses frozen recorded analysis time, including proxy "
        "preparation/decode; hashes identify the inputs.",
        "Timestamp error is the median of matched mean absolute start/end errors. "
        "Matching maximizes pair count, not global timing optimality.",
        "No footage, filenames, paths, OCR text or transcripts are included.",
        "",
        f"Manifest SHA-256: `{report['manifest_sha256']}`",
        f"Observations SHA-256: `{report['observations_sha256']}`",
        "",
    ]
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path) -> None:
    # A new directory prevents accidental replacement of user reports.
    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_text(canonical(report) + "\n", "utf-8")
    (output / "report.md").write_text(markdown(report), "utf-8")
