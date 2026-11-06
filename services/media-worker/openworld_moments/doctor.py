# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check this machine's media tools: ``python -m openworld_moments.doctor [--json]``.

Exit code 0 when media probing works, 1 otherwise. The same report is served by
the worker at ``GET /v1/capabilities``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from openworld_moments import __version__
from openworld_moments.media.tools import MediaTools


def render(report: dict[str, Any]) -> str:
    lines = [f"OpenWorld Moments worker {__version__}", ""]
    minimum = report["minimum"]
    for name in ("ffprobe", "ffmpeg"):
        tool = report[name]
        mark = "ok" if tool["status"] == "ok" else tool["status"].upper()
        line = f"  {name:<8} {mark:<9} {tool.get('version', '-')}"
        if "path" in tool:
            line += f"  ({tool['source']}: {tool['path']})"
        lines.append(line)
        if tool.get("problem"):
            lines.append(f"           {tool['problem']}")
    lines.append(
        f"  minimum  FFmpeg {minimum['ffmpeg_release']} (libavformat {minimum['libavformat']})"
    )
    lines.append("")
    yes = [k for k, v in report["decoders"].items() if v]
    no = [k for k, v in report["decoders"].items() if not v]
    lines.append(
        f"  decoders  {', '.join(yes) or '-'}" + (f"   missing: {', '.join(no)}" if no else "")
    )
    yes = [k for k, v in report["encoders"].items() if v]
    no = [k for k, v in report["encoders"].items() if not v]
    lines.append(
        f"  encoders  {', '.join(yes) or '-'}" + (f"   missing: {', '.join(no)}" if no else "")
    )
    lines.append("")
    if report["probe_ready"]:
        lines.append("Media probing: ready")
    else:
        lines.append(
            "Media probing: NOT READY. Install FFmpeg "
            f"{minimum['ffmpeg_release']} or newer and put it on PATH, or set OWM_FFPROBE."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openworld_moments.doctor")
    parser.add_argument("--json", action="store_true", help="print the machine-readable report")
    parser.add_argument("--ffprobe", help="ffprobe executable (default: OWM_FFPROBE, then PATH)")
    parser.add_argument("--ffmpeg", help="ffmpeg executable (default: OWM_FFMPEG, then PATH)")
    args = parser.parse_args(argv)
    report = MediaTools(ffprobe=args.ffprobe, ffmpeg=args.ffmpeg).capabilities()
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0 if report["probe_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
