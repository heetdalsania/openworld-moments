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
    args = parser.parse_args()
    try:
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
