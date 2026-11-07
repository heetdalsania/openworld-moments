# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI: profile validation, local analysis, and the generated synthetic example."""

from __future__ import annotations

import argparse
import contextlib
import json
import tempfile
import threading
from pathlib import Path
from typing import Any

from openworld_moments_contracts import normalize

from openworld_moments.derived.service import DerivedFailure, DerivedMedia
from openworld_moments.detectors.profiles import DEFAULT_CATALOG, ProfileCatalog, read_manifest
from openworld_moments.detectors.sdk import AnalysisError
from openworld_moments.detectors.service import Analyzer
from openworld_moments.ids import new_id
from openworld_moments.ingest.importer import Importer
from openworld_moments.media.process import ToolError, run_tool
from openworld_moments.media.tools import MediaTools
from openworld_moments.sessions.service import SessionService
from openworld_moments.storage import Database, EventRepository, StorageError


def demo(root: Path, catalog: ProfileCatalog, tools: MediaTools) -> dict[str, object]:
    """Only generated frames: no models, network, game assets, or user library."""
    clip = root / "synthetic signal.mp4"
    tool = tools.tool("ffmpeg")
    result = run_tool(
        [
            *tool.command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=320x180:r=30:d=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        timeout_s=30,
    )
    if result.returncode:
        raise AnalysisError("demo.media_failed", "Synthetic media could not be generated.")
    database = Database.open(root / "library" / "database.sqlite3")
    Importer(database, tools).run_import(
        {"paths": [str(clip)], "mode": "reference"},
        job_id=new_id("job"),
        cancel=threading.Event(),
        progress=lambda *_: None,
    )
    SessionService(database).recompute({})
    with contextlib.closing(database.connect()) as conn:
        session = SessionService(database).list_docs(conn, limit=1, offset=0)[0]
    analyzer = Analyzer(database, tools, DerivedMedia(database, tools), catalog=catalog)
    analyzed = analyzer.run(
        {"session_id": session["id"], "profile_id": "generic-open-world"}, job_id=new_id("job")
    )
    with contextlib.closing(database.connect()) as conn:
        events = [normalize(e) for e in EventRepository(conn).list_for_session(session["id"])]
    if not events:
        raise AnalysisError("demo.no_events", "Synthetic example produced no validated event.")
    return {"analysis": analyzed, "events": events}


def speech_command(args: argparse.Namespace) -> int:
    """Audio benchmark, engine check and explicit local model management (M18)."""
    from openworld_moments.transcripts.models import SpeechModels
    from openworld_moments.transcripts.service import default_engine
    from openworld_moments.transcripts.whisper import TranscriptionError

    try:
        if args.command == "audio":
            from openworld_moments.detectors.audio_benchmark import benchmark as audio_benchmark

            result = audio_benchmark(args.minutes, args.repeats)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["budget_2x_met"] else 1
        if args.command == "speech":
            engine = default_engine()
            print(
                json.dumps({"available": True, "engine": "whisper.cpp", "version": engine.version})
            )
            return 0
        models = SpeechModels(args.library)
        if args.operation == "install":
            output: Any = models.install(args.file, args.name, args.license).public()
        elif args.operation == "remove":
            models.remove(args.name)
            output = {"removed": args.name}
        else:
            output = [m.public() for m in models.installed()]
        print(json.dumps(output, sort_keys=True))
        return 0
    except TranscriptionError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="owm")
    sub = parser.add_subparsers(dest="command", required=True)
    profiles = sub.add_parser("profiles").add_subparsers(dest="operation", required=True)
    validate = profiles.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--profiles", type=Path, default=DEFAULT_CATALOG)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("session_id")
    analyze.add_argument("--library", type=Path, required=True)
    analyze.add_argument("--profile", dest="profile_id", required=True)
    analyze.add_argument("--locale")
    analyze.add_argument("--force", action="store_true")
    analyze.add_argument("--profiles", type=Path, default=DEFAULT_CATALOG)
    example = sub.add_parser("demo")
    example.add_argument("--profiles", type=Path, default=DEFAULT_CATALOG)
    wanted = sub.add_parser("wanted").add_subparsers(dest="operation", required=True)
    replay = wanted.add_parser("replay")
    replay.add_argument("asset_id")
    replay.add_argument("--library", type=Path, required=True)
    replay.add_argument("--profile", dest="profile_id", default="generic-wanted")
    replay.add_argument("--profiles", type=Path, default=DEFAULT_CATALOG)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--crops", action="store_true", help="Write separate local evidence crops")
    bench = wanted.add_parser("benchmark")
    bench.add_argument("--seconds", type=int, default=3600)
    bench.add_argument("--repeats", type=int, default=5)
    text_cli = sub.add_parser("text").add_subparsers(dest="operation", required=True)
    doctor = text_cli.add_parser("doctor")
    doctor.add_argument("--language", default="eng")
    text_bench = text_cli.add_parser("benchmark")
    text_bench.add_argument("--samples", type=int, default=60)
    text_bench.add_argument("--repeats", type=int, default=3)
    audio_cli = sub.add_parser("audio").add_subparsers(dest="operation", required=True)
    audio_bench = audio_cli.add_parser("benchmark")
    audio_bench.add_argument("--minutes", type=int, default=10)
    audio_bench.add_argument("--repeats", type=int, default=3)
    speech_cli = sub.add_parser("speech").add_subparsers(dest="operation", required=True)
    speech_cli.add_parser("doctor")
    models_cli = sub.add_parser("models").add_subparsers(dest="operation", required=True)
    for name in ("list", "install", "remove"):
        command = models_cli.add_parser(name)
        command.add_argument("--library", type=Path, required=True)
        if name != "list":
            command.add_argument("name", help="Model name, e.g. base.en")
        if name == "install":
            command.add_argument("file", type=Path, help="A local whisper.cpp ggml model file")
            command.add_argument("--license", required=True, help="The model's license, e.g. MIT")
    from openworld_moments.evaluation.cli import arguments as eval_arguments

    eval_arguments(sub)
    from openworld_moments.stories.cli import arguments as story_arguments

    story_arguments(sub)
    args = parser.parse_args()
    try:
        if args.command in ("story", "story-review", "story-golden"):
            from openworld_moments.stories.cli import command as story_command

            return story_command(args)
        if args.command == "eval":
            from openworld_moments.evaluation.cli import command as evaluate_command

            return evaluate_command(args)
        if args.command in ("audio", "speech", "models"):
            return speech_command(args)
        if args.command == "text":
            from openworld_moments.detectors.ocr import Tesseract
            from openworld_moments.detectors.text_benchmark import benchmark as text_benchmark

            if args.operation == "doctor":
                result = {
                    "available": True,
                    "tool_versions": Tesseract().prepare(args.language, threading.Event()),
                }
                print(json.dumps(result, sort_keys=True))
                return 0
            result = text_benchmark(args.samples, args.repeats)
            print(json.dumps(result, sort_keys=True))
            return (
                0 if result["budget_2x_met"] and result["correct_categories"] == args.samples else 1
            )
        if args.command == "wanted":
            from openworld_moments.detectors.wanted_replay import benchmark
            from openworld_moments.detectors.wanted_replay import replay as run_replay

            if args.operation == "benchmark":
                result = benchmark(args.seconds, args.repeats)
                print(json.dumps(result, sort_keys=True))
                return 0 if result["budget_2x_met"] else 1
            result = run_replay(
                args.asset_id,
                args.library,
                args.profile_id,
                ProfileCatalog(args.profiles),
                args.output,
                crops=args.crops,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        catalog = ProfileCatalog(args.profiles)
        if args.command == "profiles":
            resolved = catalog.resolve(read_manifest(args.manifest))
            output: dict[str, Any] = {
                "valid": True,
                "profile": resolved.document(),
                "digest": resolved.key,
            }
        elif args.command == "demo":
            with tempfile.TemporaryDirectory(prefix="owm-demo-") as tmp:
                output = demo(Path(tmp), catalog, MediaTools())
        else:
            database = Database.open(args.library / "database.sqlite3")
            tools = MediaTools()
            analyzer = Analyzer(database, tools, DerivedMedia(database, tools), catalog=catalog)
            params = {
                "session_id": args.session_id,
                "profile_id": args.profile_id,
                "force": args.force,
                **({"locale": args.locale} if args.locale else {}),
            }
            output = analyzer.run(params, job_id=new_id("job"))
        print(json.dumps(output, sort_keys=True))
        outcomes = output.get("outcomes", [])
        return int(any(o["status"] in ("failed", "skipped") for o in outcomes))
    except (AnalysisError, DerivedFailure, ToolError, StorageError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, AnalysisError) else "command.failed"
        message = exc.message if isinstance(exc, AnalysisError) else "The local command failed."
        print(json.dumps({"error": {"code": code, "message": message}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
