# SPDX-License-Identifier: AGPL-3.0-or-later
"""Eval CLI: generate holdout, capture private local replay, evaluate frozen inputs."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path
from typing import Any

from openworld_moments.detectors.profiles import ProfileCatalog, canonical
from openworld_moments.detectors.sdk import AnalysisCancelled
from openworld_moments.evaluation.capture import capture
from openworld_moments.evaluation.holdout import generate
from openworld_moments.evaluation.service import (
    EvaluationError,
    evaluate,
    read_document,
    write_report,
)
from openworld_moments.media.tools import MediaTools


def arguments(sub: Any) -> None:
    operations = sub.add_parser("eval").add_subparsers(dest="operation", required=True)
    holdout = operations.add_parser("holdout")
    holdout.add_argument("--output", type=Path, required=True)
    for name in ("capture", "run"):
        command = operations.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name == "capture":
            command.add_argument("--media-map", type=Path, required=True)
            command.add_argument("--profiles", type=Path)
        else:
            command.add_argument("--observations", type=Path, required=True)


def command(args: argparse.Namespace) -> int:
    cancel = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        if args.operation == "holdout":
            result = generate(args.output, MediaTools())
            print(json.dumps({"dataset_id": result["dataset_id"], "clips": len(result["clips"])}))
        elif args.operation == "capture":
            manifest = read_document(args.manifest, "evaluation")
            if args.output.exists():
                raise EvaluationError("evaluation.output_exists", "Choose a new observations file.")
            result = capture(
                manifest,
                args.media_map,
                MediaTools(),
                ProfileCatalog(args.profiles) if args.profiles else None,
                cancel,
            )
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(canonical(result) + "\n")
            print(json.dumps({"clips": len(result["clips"]), "captured": True}))
        else:
            result = evaluate(
                read_document(args.manifest, "evaluation"),
                read_document(args.observations, "evaluation-observations"),
                cancel,
            )
            write_report(result, args.output)
            print(canonical(result))
        return 0
    except AnalysisCancelled:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "evaluation.cancelled",
                        "message": "Evaluation cancelled; completed source files are untouched.",
                    }
                }
            )
        )
        return 130
    except Exception as exc:
        code = exc.code if isinstance(exc, EvaluationError) else "evaluation.failed"
        message = (
            exc.message
            if isinstance(exc, EvaluationError)
            else "Local evaluation failed. Check inputs and choose a new output location."
        )
        print(json.dumps({"error": {"code": code, "message": message}}))
        return 1
    finally:
        signal.signal(signal.SIGINT, previous)
