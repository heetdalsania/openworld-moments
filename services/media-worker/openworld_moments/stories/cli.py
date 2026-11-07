# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit local story generation, review and synthetic coverage report."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path
from typing import Any

from openworld_moments.detectors.profiles import canonical
from openworld_moments.storage import Database
from openworld_moments.stories.algorithm import PRESETS
from openworld_moments.stories.service import (
    StoryCancelled,
    StoryDecision,
    StoryError,
    StoryRequest,
    StoryService,
)


def arguments(sub: Any) -> None:
    story = sub.add_parser("story")
    story.add_argument("session_id")
    story.add_argument("--library", type=Path, required=True)
    story.add_argument("--preset", choices=tuple(PRESETS), default="short")
    story.add_argument("--pre-roll-ms", type=int)
    story.add_argument("--post-roll-ms", type=int)
    story.add_argument("--merge-gap-ms", type=int)
    story.add_argument("--avoid-spoilers", action="store_true")
    story.add_argument("--reviewed-only", action="store_true")
    story.add_argument("--force", action="store_true")
    story.add_argument("--list", action="store_true", help="Read without generating")
    story.add_argument(
        "--history", action="store_true", help="Include rejected and stale candidates"
    )
    story.add_argument("--offset", type=int, default=0)
    review = sub.add_parser("story-review")
    review.add_argument("session_id")
    review.add_argument("candidate_id")
    review.add_argument("--library", type=Path, required=True)
    review.add_argument("--state", choices=("suggested", "accepted", "rejected"), required=True)
    review.add_argument("--input-key", required=True)
    review.add_argument("--expected-revision", type=int, required=True)
    golden = sub.add_parser("story-golden")
    golden.add_argument("--output", type=Path, required=True)


def command(args: argparse.Namespace) -> int:
    cancel = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        if args.command == "story-golden":
            from openworld_moments.stories.golden import evaluate, markdown

            result = evaluate()
            args.output.mkdir(parents=True, exist_ok=False)
            (args.output / "report.json").write_text(canonical(result) + "\n", "utf-8")
            (args.output / "report.md").write_text(markdown(result), "utf-8")
            print(canonical(result))
            return 0 if result["passed"] == result["total"] else 1
        database_path = args.library / "database.sqlite3"
        if not database_path.is_file():
            raise StoryError("story.library_missing", "Select an existing local library.", 404)
        service = StoryService(Database.open(database_path))
        if args.command == "story-review":
            result = service.decide(
                args.session_id,
                args.candidate_id,
                StoryDecision(
                    state=args.state,
                    input_key=args.input_key,
                    expected_revision=args.expected_revision,
                ),
            )
        else:
            request = StoryRequest(
                preset=args.preset,
                pre_roll_ms=args.pre_roll_ms,
                post_roll_ms=args.post_roll_ms,
                merge_gap_ms=args.merge_gap_ms,
                avoid_spoilers=args.avoid_spoilers,
                allow_unreviewed=not args.reviewed_only,
                force=args.force,
            )
            if not args.list:
                service.generate(args.session_id, request, cancel=cancel)
            result = service.page(
                args.session_id, request, include_history=args.history, offset=args.offset
            )
        print(canonical(result))
        return 0
    except StoryCancelled:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "story.cancelled",
                        "message": ("Story generation cancelled; previous candidates are kept."),
                    }
                }
            )
        )
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": exc.code if isinstance(exc, StoryError) else "story.failed",
                        "message": exc.message
                        if isinstance(exc, StoryError)
                        else (
                            "Local story operation failed. "
                            "Check the selected library and arguments."
                        ),
                    }
                }
            )
        )
        return 1
    finally:
        signal.signal(signal.SIGINT, previous)
