# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render plan IR (plan_version 1) and its compilation to an FFmpeg argument array.

Everything here is pure: a validated editor document, source facts, a preset and an
encoder become a normalized plan, and the plan becomes an argument template whose
inputs and output are placeholders (``{source:N}``, ``{output}``). Only numbers and
constants enter the filter graph; titles, captions, overlay text and file names
never do. See docs/architecture/render.md.
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments.derived.tonemap import ToneMapSettings
from openworld_moments.render.encoders import EncoderSpec, video_args

ENGINE_VERSION = "1.0.0"
AUDIO_RATE = 48000
#: One FFmpeg input per segment piece; bounded for argv length (Windows: 32 767 chars).
MAX_PIECES = 120
MAX_ARGV_CHARS = 30_000
MAX_BLURS = 100
MAX_AUDIO_RANGES = 500
MIN_BLUR_PX = 8
#: Read a little past each piece so trims always find enough frames and samples.
READ_MARGIN_MS = 1000
LUT_NAMES = {"smpte2084": "tonemap-pq.cube", "arib-std-b67": "tonemap-hlg.cube"}


class RenderError(Exception):
    """A safe, user-facing refusal or failure. Messages never contain paths or text."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details = details or {}


@dataclass(frozen=True)
class SourceFacts:
    """What the plan needs to know about one referenced original."""

    asset_id: str
    sha256: str
    original_name: str
    audio: bool
    fps: tuple[int, int] | None
    tone_map: ToneMapSettings | None


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def _frames_at(ms: int, fps: tuple[int, int]) -> int:
    return round(ms * fps[0] / (fps[1] * 1000))


def _samples_at(ms: int) -> int:
    return ms * AUDIO_RATE // 1000


def _region_at(crop: dict[str, Any], offset: int) -> list[float] | None:
    """Keyframes hold until the next one; before the first, the crop mode applies."""
    region = None
    for keyframe in crop["keyframes"]:
        if keyframe["at_ms"] <= offset:
            region = keyframe["region"]
    return region


def build_plan(
    document: dict[str, Any],
    facts: dict[str, SourceFacts],
    preset: dict[str, Any],
    encoder: EncoderSpec,
    *,
    ffmpeg_version: str,
    omit_text: bool = False,
) -> dict[str, Any]:
    project = document["project"]
    segments = project["tracks"][0]["segments"] if project["tracks"] else []
    if not segments:
        raise RenderError("render.empty_project", "Add at least one clip before rendering.")
    if preset["video"]["codec"] != "h264":
        raise RenderError("render.preset_unsupported", "This version renders H.264 only.")

    notes: list[str] = []
    omitted: list[str] = []
    texts = [o for o in project.get("overlays", []) if o["kind"] == "text"]
    settings = project.get("caption_settings")
    burned = bool(settings and settings["burn_in"] and project.get("captions"))
    missing = (["text_overlays"] if texts else []) + (["burned_captions"] if burned else [])
    if missing and not omit_text:
        raise RenderError(
            "render.text_unsupported",
            "This version cannot draw text overlays or burned-in captions yet. Render "
            "without them explicitly, or remove them from the project.",
            details={"omitted": missing},
        )
    if missing:
        omitted = missing
        notes.append("Text overlays and burned-in captions were left out at your request.")

    order: list[str] = []
    for segment in segments:
        if segment["asset_id"] not in order:
            order.append(segment["asset_id"])
    index = {aid: i for i, aid in enumerate(order)}
    first = facts[segments[0]["asset_id"]]
    fps = (
        (preset["fps"]["num"], preset["fps"]["den"])
        if isinstance(preset["fps"], dict)
        else (first.fps or (30, 1))
    )
    if preset["fps"] == "source" and first.fps is None:
        notes.append("The first clip's frame rate is unknown; rendering at 30 fps.")

    pieces: list[dict[str, Any]] = []
    for segment in segments:
        crop = segment["crop"]
        start, length = (
            segment["timeline_start_ms"],
            segment["source_out_ms"] - segment["source_in_ms"],
        )
        cuts = sorted({0, *(k["at_ms"] for k in crop["keyframes"] if 0 < k["at_ms"] < length)})
        for i, offset in enumerate(cuts):
            end = cuts[i + 1] if i + 1 < len(cuts) else length
            region = _region_at(crop, offset)
            mode = crop["mode"]
            piece_crop: dict[str, Any] = {"mode": "manual" if region else mode}
            if region:
                piece_crop["region"] = list(region)
            if mode == "safe" and not region:
                piece_crop["mode"] = "safe"
            pieces.append(
                {
                    "source": index[segment["asset_id"]],
                    "in_ms": segment["source_in_ms"] + offset,
                    "out_ms": segment["source_in_ms"] + end,
                    "timeline_start_ms": start + offset,
                    "crop": piece_crop,
                }
            )
    if any(p["crop"]["mode"] == "safe" for p in pieces):
        notes.append("HUD-aware 'safe' layouts arrive in M25; those clips render as 'fit'.")

    # Exact cumulative frame and sample counts: no drift across pieces.
    merged: list[dict[str, Any]] = []
    for piece in pieces:
        end = piece["timeline_start_ms"] + piece["out_ms"] - piece["in_ms"]
        frames = _frames_at(end, fps) - _frames_at(piece["timeline_start_ms"], fps)
        if frames < 1 and merged and merged[-1]["source"] == piece["source"]:
            # Shorter than a frame: fold into the previous piece of the same clip.
            merged[-1]["out_ms"] = piece["out_ms"]
            continue
        merged.append(piece)
    for piece in merged:
        start = piece["timeline_start_ms"]
        end = start + piece["out_ms"] - piece["in_ms"]
        piece["frames"] = max(1, _frames_at(end, fps) - _frames_at(start, fps))
        piece["samples"] = max(1, _samples_at(end) - _samples_at(start))
    if len(merged) > MAX_PIECES:
        raise RenderError(
            "render.too_complex",
            f"This version renders up to {MAX_PIECES} clips and crop changes at once.",
        )

    blurs = [
        {"start_ms": o["start_ms"], "end_ms": o["end_ms"], "region": list(o["region"])}
        for o in project.get("overlays", [])
        if o["kind"] == "blur"
    ]
    audio = project["audio"]
    ranges = len(audio["mute_ranges"]) + len(audio.get("gain_ranges", []))
    if len(blurs) > MAX_BLURS or ranges > MAX_AUDIO_RANGES:
        raise RenderError(
            "render.too_complex",
            "This project has more privacy blurs or audio ranges than supported.",
        )
    used = [facts[aid] for aid in order]
    if any(f.tone_map for f in used):
        notes.append("HDR clips are tone-mapped to standard range (BT.709).")
    plan: dict[str, Any] = {
        "plan_version": 1,
        "preset": preset,
        "encoder": {"id": encoder.id, "kind": encoder.kind},
        "output": {
            "width": preset["width"],
            "height": preset["height"],
            "fps": {"num": fps[0], "den": fps[1]},
            "audio": any(f.audio for f in used),
        },
        "duration_ms": sum(p["out_ms"] - p["in_ms"] for p in merged),
        "sources": [
            {
                "index": i,
                "asset_id": f.asset_id,
                "sha256": f.sha256,
                "original_name": f.original_name,
                "audio": f.audio,
                "tone_mapped": f.tone_map is not None,
            }
            for i, f in enumerate(used)
        ],
        "segments": merged,
        "audio": {
            "gain_db": audio["gain_db"],
            "gain_ranges": [dict(r) for r in audio.get("gain_ranges", [])],
            "mute_ranges": [dict(r) for r in audio["mute_ranges"]],
        },
        "blur_overlays": blurs,
        "omitted": omitted,
        "notes": notes,
        "tools": {"ffmpeg": ffmpeg_version, "render_engine": ENGINE_VERSION},
    }
    if encoder.quality_note:
        plan["encoder"]["quality_note"] = encoder.quality_note
    argv, graph = compile_plan(plan, used, encoder)
    plan["command"] = {"argv": argv, "filter_complex": graph}
    return plan


def _video_chain(
    piece: dict[str, Any], source: SourceFacts, width: int, height: int, fps: tuple[int, int]
) -> list[str]:
    steps: list[str] = []
    if source.tone_map is not None:
        steps += [
            "scale=in_color_matrix=bt2020:in_range=tv",
            "format=gbrp16le",
            f"lut3d=file={LUT_NAMES[source.tone_map.transfer]}:interp={source.tone_map.interpolation}",
            "scale=out_color_matrix=bt709:out_range=tv",
            "format=yuv420p",
            "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
        ]
    steps.append("setpts=PTS-STARTPTS")
    crop = piece["crop"]
    if "region" in crop:
        x, y, w, h = crop["region"]
        steps.append(f"crop=w=iw*{w:.6f}:h=ih*{h:.6f}:x=iw*{x:.6f}:y=ih*{y:.6f}:exact=1")
    if crop["mode"] == "fill":
        steps.append(
            f"scale=w={width}:h={height}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={width}:{height}"
        )
    else:  # fit, safe (M25 adds HUD-aware safe layouts) and manual regions
        steps.append(
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease:"
            f"force_divisible_by=2:flags=bicubic,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    steps += [
        "setsar=1",
        f"fps={fps[0]}/{fps[1]}",
        "tpad=stop_mode=clone:stop_duration=2",
        f"trim=end_frame={piece['frames']}",
        "setpts=PTS-STARTPTS",
        "format=yuv420p",
    ]
    return steps


def _between(ranges: list[dict[str, Any]]) -> str:
    return "+".join(f"between(t,{_seconds(r['start_ms'])},{_seconds(r['end_ms'])})" for r in ranges)


def compile_plan(
    plan: dict[str, Any], sources: list[SourceFacts], encoder: EncoderSpec
) -> tuple[list[str], str]:
    width, height = plan["output"]["width"], plan["output"]["height"]
    fps = (plan["output"]["fps"]["num"], plan["output"]["fps"]["den"])
    with_audio = plan["output"]["audio"]
    inputs: list[str] = []
    graph: list[str] = []
    count = 0
    labels: list[str] = []
    for k, piece in enumerate(plan["segments"]):
        source = sources[piece["source"]]
        read = _seconds(piece["out_ms"] - piece["in_ms"] + READ_MARGIN_MS)
        inputs += [
            "-ss",
            _seconds(piece["in_ms"]),
            "-t",
            read,
            "-i",
            f"{{source:{piece['source']}}}",
        ]
        video_input = count
        count += 1
        chain = ",".join(_video_chain(piece, source, width, height, fps))
        graph.append(f"[{video_input}:v:0]{chain}[v{k}]")
        labels.append(f"[v{k}]")
        if with_audio:
            samples = piece["samples"]
            if source.audio:
                graph.append(
                    f"[{video_input}:a:0]aresample={AUDIO_RATE},"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                    f"apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS[a{k}]"
                )
            else:  # silence for a clip without audio keeps the track continuous
                inputs += [
                    "-f",
                    "lavfi",
                    "-t",
                    read,
                    "-i",
                    f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}",
                ]
                graph.append(
                    f"[{count}:a:0]aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"atrim=end_sample={samples},asetpts=PTS-STARTPTS[a{k}]"
                )
                count += 1
            labels.append(f"[a{k}]")
    n = len(plan["segments"])
    blurs = plan["blur_overlays"]
    video_out = "vc" if blurs else "vout"
    graph.append(
        "".join(labels)
        + f"concat=n={n}:v=1:a={1 if with_audio else 0}[{video_out}]"
        + ("[ac]" if with_audio else "")
    )
    current = video_out
    for b, blur in enumerate(blurs):
        x, y, w, h = blur["region"]
        px, py = math.floor(x * width), math.floor(y * height)
        # At least MIN_BLUR_PX, shifted (not shrunk) to stay inside the frame.
        pw = min(width, max(MIN_BLUR_PX, round(w * width)))
        ph = min(height, max(MIN_BLUR_PX, round(h * height)))
        px, py = min(px, width - pw), min(py, height - ph)
        radius = max(1, min(pw, ph) // 4)
        chroma = max(1, min(pw, ph) // 8)
        target = "vout" if b == len(blurs) - 1 else f"vb{b}"
        span = f"between(t,{_seconds(blur['start_ms'])},{_seconds(blur['end_ms'])})"
        graph.append(
            f"[{current}]split=2[bm{b}][bs{b}];"
            f"[bs{b}]crop=w={pw}:h={ph}:x={px}:y={py},"
            f"boxblur=luma_radius={radius}:luma_power=3:chroma_radius={chroma}:chroma_power=3[bb{b}];"
            f"[bm{b}][bb{b}]overlay=x={px}:y={py}:enable='{span}'[{target}]"
        )
        current = target
    if with_audio:
        audio = plan["audio"]
        steps = [f"asetnsamples=n={AUDIO_RATE // 100}:p=0"]  # 10 ms gain/mute resolution
        if audio["gain_ranges"]:
            steps.append(
                f"volume=volume={audio['gain_db']}dB:enable='not({_between(audio['gain_ranges'])})'"
            )
        elif audio["gain_db"] != 0:
            steps.append(f"volume=volume={audio['gain_db']}dB")
        for r in audio["gain_ranges"]:
            steps.append(f"volume=volume={r['gain_db']}dB:enable='{_between([r])}'")
        for r in audio["mute_ranges"]:  # mute dominates
            steps.append(f"volume=volume=0:enable='{_between([r])}'")
        graph.append("[ac]" + ",".join(steps) + "[aout]")
    preset = plan["preset"]
    argv = [
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        "file,pipe,lavfi",
        *inputs,
        *graph_option(plan["tools"]["ffmpeg"]),
        "-map",
        "[vout]",
        *(["-map", "[aout]"] if with_audio else ["-an"]),
        *video_args(encoder, preset),
        *(
            [
                "-c:a",
                "aac",
                "-b:a",
                f"{preset['audio']['bitrate_kbps']}k",
                "-ar",
                str(AUDIO_RATE),
                "-ac",
                "2",
            ]
            if with_audio
            else []
        ),
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
        "{output}",
    ]
    return argv, ";\n".join(graph)


def graph_option(ffmpeg_version: str) -> list[str]:
    """Read the filter graph from ``graph.txt`` in the working folder. FFmpeg 7 added
    ``-/filter_complex <file>``; FFmpeg 8 removed ``-filter_complex_script``."""
    match = re.match(r"n?(\d+)\.", ffmpeg_version)
    if match and int(match[1]) >= 7:
        return ["-/filter_complex", "graph.txt"]
    return ["-filter_complex_script", "graph.txt"]


def materialize(template: list[str], sources: list[Path], output: Path) -> list[str]:
    """Replace placeholders with ``file:`` URLs. Paths are argv elements, never shell text."""
    argv = []
    for arg in template:
        if arg.startswith("{source:") and arg.endswith("}"):
            argv.append(f"file:{sources[int(arg[8:-1])]}")
        elif arg == "{output}":
            argv.append(f"file:{output}")
        else:
            argv.append(arg)
    if sys.platform == "win32" and sum(len(a) + 3 for a in argv) > MAX_ARGV_CHARS:
        raise RenderError(
            "render.too_complex", "This project has too many clips for one render on Windows."
        )
    return argv
