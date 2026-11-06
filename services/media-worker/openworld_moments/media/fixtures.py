# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate tiny synthetic media fixtures with FFmpeg (M04).

All content comes from FFmpeg's built-in test sources (``testsrc2``, ``sine``),
so fixtures contain no real footage and are never committed. Generate them on
demand::

    uv run --directory services/media-worker python -m openworld_moments.media.fixtures OUT_DIR

Each fixture is about one second long. HEVC fixtures are produced only when
the FFmpeg build has ``libx265``; the manifest records what was skipped.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from openworld_moments.media.process import ToolError, run_tool
from openworld_moments.media.tools import MediaTools, ToolInfo, list_codecs

TIMEOUT_S = 120.0
_VIDEO = "testsrc2=size=320x180:rate=30000/1001:duration=1"
_AUDIO = "sine=frequency=440:sample_rate=48000:duration=1"


@dataclass(frozen=True)
class Fixture:
    name: str
    #: What a probe must report, checked by the fixture matrix tests.
    expect: dict[str, object]
    requires: tuple[str, ...] = ("libx264",)


class FixtureError(Exception):
    pass


def _x264(*extra: str) -> list[str]:
    return ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *extra]


def _lavfi(video: str = _VIDEO, audio: str | None = _AUDIO) -> list[str]:
    args = ["-f", "lavfi", "-i", video]
    if audio:
        args += ["-f", "lavfi", "-i", audio]
    return args


_AAC = ["-c:a", "aac", "-b:a", "64k", "-ac", "2"]

#: name → (ffmpeg arguments after inputs, expectations)
FIXTURES: tuple[Fixture, ...] = (
    Fixture("h264_aac.mp4", {"video_codec": "h264", "audio": 1, "frame_rate": (30000, 1001)}),
    Fixture("h264_aac.mov", {"video_codec": "h264", "audio": 1}),
    Fixture("h264_aac.mkv", {"video_codec": "h264", "audio": 1}),
    Fixture("h264_aac.ts", {"video_codec": "h264", "audio": 1}),
    Fixture("no_audio.mp4", {"video_codec": "h264", "audio": 0}),
    Fixture("vfr.mp4", {"video_codec": "h264", "variable_frame_rate": True}),
    Fixture("rotated.mp4", {"video_codec": "h264", "rotation": 270}),
    Fixture("hdr_pq.mp4", {"video_codec": "h264", "hdr": True, "transfer": "smpte2084"}),
    Fixture("hevc.mp4", {"video_codec": "hevc", "audio": 1}, requires=("libx265",)),
    Fixture("audio_only.m4a", {"error": "media.no_video_stream"}, requires=()),
    Fixture("still.png", {"error": "media.still_image"}, requires=()),
    Fixture("truncated.mp4", {"error": "media.damaged"}),
    Fixture("garbage.mp4", {"error": "media.damaged"}, requires=()),
    Fixture("garbage.bin", {"error": "media.unsupported_format"}, requires=()),
    Fixture("empty.mp4", {"error": "media.empty_file"}, requires=()),
)


def _ffmpeg(tool: ToolInfo, args: Sequence[str]) -> None:
    argv = [*tool.command, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args]
    try:
        result = run_tool(argv, timeout_s=TIMEOUT_S)
    except ToolError as exc:
        raise FixtureError(f"ffmpeg failed: {exc}\n{exc.stderr_tail}") from exc
    if result.returncode != 0:
        raise FixtureError(f"ffmpeg exited {result.returncode}\n{result.stderr_tail}")


def _builders(ffmpeg: ToolInfo, out: Path) -> dict[str, Callable[[Path], None]]:
    def run(*args: str) -> Callable[[Path], None]:
        return lambda target: _ffmpeg(ffmpeg, [*args, str(target)])

    def rotated(target: Path) -> None:
        plain = out / ".rotated-source.mp4"
        _ffmpeg(ffmpeg, [*_lavfi(), *_x264(), *_AAC, "-shortest", str(plain)])
        # -display_rotation is counter-clockwise; a probe reports clockwise (270).
        _ffmpeg(ffmpeg, ["-display_rotation", "90", "-i", str(plain), "-c", "copy", str(target)])
        plain.unlink()

    def truncated(target: Path) -> None:
        # Without +faststart the index (moov) is written last, so cutting the file
        # in half loses it: the classic "recording was interrupted" damage.
        whole = out / ".truncated-source.mp4"
        _ffmpeg(ffmpeg, [*_lavfi(), *_x264(), *_AAC, "-shortest", str(whole)])
        data = whole.read_bytes()
        target.write_bytes(data[: len(data) // 2])
        whole.unlink()

    def garbage(target: Path) -> None:
        target.write_bytes(random.Random(target.name).randbytes(64 * 1024))  # noqa: S311

    return {
        "h264_aac.mp4": run(*_lavfi(), *_x264(), *_AAC, "-shortest", "-movflags", "+faststart"),
        "h264_aac.mov": run(*_lavfi(), *_x264(), *_AAC, "-shortest"),
        "h264_aac.mkv": run(*_lavfi(), *_x264(), *_AAC, "-shortest"),
        "h264_aac.ts": run(*_lavfi(), *_x264(), *_AAC, "-shortest", "-f", "mpegts"),
        "no_audio.mp4": run(*_lavfi(audio=None), *_x264()),
        # 60 fps for the first half second, then every third frame (20 fps).
        "vfr.mp4": run(
            *_lavfi("testsrc2=size=320x180:rate=60:duration=1", None),
            "-vf",
            "select='lt(n\\,30)+not(mod(n\\,3))'",
            "-fps_mode",
            "vfr",
            *_x264(),
        ),
        "rotated.mp4": rotated,
        # PQ/BT.2020 tags on an 8-bit stream: enough to prove color metadata survives.
        # Frames are tagged (setparams) so every FFmpeg version carries the tags into
        # the bitstream and container; encoder-level -color_* flags are not enough on 7+.
        "hdr_pq.mp4": run(
            *_lavfi(),
            "-vf",
            "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv",
            *_x264(),
            *_AAC,
            "-shortest",
        ),
        "hevc.mp4": run(
            *_lavfi(),
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-x265-params",
            "log-level=error",
            "-pix_fmt",
            "yuv420p",
            "-tag:v",
            "hvc1",
            *_AAC,
            "-shortest",
        ),
        "audio_only.m4a": run("-f", "lavfi", "-i", _AUDIO, *_AAC),
        "still.png": run("-f", "lavfi", "-i", _VIDEO, "-frames:v", "1", "-update", "1"),
        "truncated.mp4": truncated,
        "garbage.mp4": garbage,
        "garbage.bin": garbage,
        "empty.mp4": lambda target: target.write_bytes(b""),
    }


def generate(out: Path, ffmpeg: ToolInfo) -> dict[str, object]:
    """Write every fixture the FFmpeg build supports into ``out``; return a manifest."""
    if not ffmpeg.ok:
        raise FixtureError(f"ffmpeg is not usable: {ffmpeg.problem}")
    out.mkdir(parents=True, exist_ok=True)
    encoders = list_codecs(ffmpeg, "encoders")
    builders = _builders(ffmpeg, out)
    generated: dict[str, dict[str, object]] = {}
    skipped: dict[str, str] = {}
    for fixture in FIXTURES:
        missing = [r for r in fixture.requires if r not in encoders]
        if missing:
            skipped[fixture.name] = f"ffmpeg lacks {', '.join(missing)}"
            continue
        builders[fixture.name](out / fixture.name)
        generated[fixture.name] = fixture.expect
    manifest: dict[str, object] = {
        "ffmpeg_version": ffmpeg.version,
        "generated": generated,
        "skipped": skipped,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m openworld_moments.media.fixtures",
        description="Generate synthetic media fixtures (never commit the output).",
    )
    parser.add_argument("out", type=Path, help="output directory")
    parser.add_argument("--ffmpeg", help="ffmpeg executable (default: OWM_FFMPEG, then PATH)")
    args = parser.parse_args(argv)
    try:
        manifest = generate(args.out, MediaTools(ffmpeg=args.ffmpeg).tool("ffmpeg"))
    except FixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
