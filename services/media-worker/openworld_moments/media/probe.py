# SPDX-License-Identifier: AGPL-3.0-or-later
"""Probe one local media file with FFprobe and normalize the result (M04).

The source is only read: it is opened read-only for a pre-check and FFprobe
reads its header. Nothing is written next to it and its bytes and
modification time are unchanged.

Normalization keeps only the fields of the contract ``MediaProbe``. The path
and free-form container tags (titles, encoder strings, GPS) are never copied.
Frame rates stay exact rationals. Failures raise :class:`ProbeError` with a
stable code (see ``docs/architecture/media.md``).
"""

from __future__ import annotations

import json
import stat
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

from openworld_moments_contracts.generated.media_asset_schema import MediaProbe

from openworld_moments.media.process import (
    ToolCancelled,
    ToolNotStarted,
    ToolOutputTooLarge,
    ToolTimeout,
    run_tool,
)
from openworld_moments.media.tools import MIN_FFMPEG_RELEASE, ToolInfo
from openworld_moments.redaction import Redactor

DEFAULT_TIMEOUT_S = 30.0
MAX_PATH_CHARS = 4096
MAX_DIMENSION = 16384
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
_UNKNOWN = frozenset({"", "unknown", "unspecified", "reserved", "N/A"})
_STILL_FORMATS = frozenset({"image2", "png", "apng", "bmp", "tiff", "webp"})
#: Extensions that claim to be video; unreadable files with these are 'damaged'.
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".ts", ".m2ts", ".mts", ".avi", ".flv", ".3gp"}
)
#: FFprobe messages that mean "recognized, but broken or incomplete".
_DAMAGE_MARKERS = (
    "moov atom not found",
    "partial file",
    "truncat",
    "corrupt",
    "invalid nal",
    "error reading header",
    "ebml header parsing failed",
    "end of file",
    "could not find codec parameters",
)
#: FFmpeg's AVERROR_INVALIDDATA.
AVERROR_INVALIDDATA = -1094995529
#: stdout cap for FFprobe JSON. Real files stay far below this.
MAX_PROBE_OUTPUT = 4 * 1024 * 1024


class ProbeError(Exception):
    """A probe failed. ``code`` is stable and safe to show; ``message`` never has the path."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        stderr_tail: str = "",
        details: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.stderr_tail = stderr_tail
        self.details = dict(details or {})


# -- input checks ---------------------------------------------------------------------


def check_path_param(value: object) -> str:
    """Validate a ``path`` job parameter. Raises ValueError (→ job.invalid_params)."""
    if not isinstance(value, str) or not value:
        raise ValueError("'path' must be a non-empty string")
    if len(value) > MAX_PATH_CHARS or "\0" in value:
        raise ValueError("'path' is too long or contains a NUL character")
    if not Path(value).is_absolute():
        raise ValueError("'path' must be absolute")
    return value


def precheck(path: Path) -> int:
    """Fail fast with a precise code before starting FFprobe. Returns the size in bytes."""
    try:
        info = path.stat()  # follows symlinks: the target must be a regular file
    except FileNotFoundError as exc:
        raise ProbeError("media.not_found", "The file does not exist.") from exc
    except PermissionError as exc:
        raise ProbeError(
            "media.permission_denied", "The file cannot be read (permission denied)."
        ) from exc
    except OSError as exc:
        raise ProbeError("media.unreadable", f"The file cannot be read: {exc.strerror}.") from exc
    from openworld_moments.media.availability import DOWNLOAD_REQUIRED, cloud_only

    if cloud_only(info):
        raise ProbeError("media.download_required", DOWNLOAD_REQUIRED, retryable=True)
    if not stat.S_ISREG(info.st_mode):
        raise ProbeError("media.not_a_file", "The path is not a regular file.")
    if info.st_size == 0:
        raise ProbeError("media.empty_file", "The file is empty.")
    try:
        with path.open("rb") as handle:  # read-only open: proves readability, changes nothing
            handle.read(1)
    except PermissionError as exc:
        raise ProbeError(
            "media.permission_denied", "The file cannot be read (permission denied)."
        ) from exc
    except OSError as exc:
        raise ProbeError("media.unreadable", f"The file cannot be read: {exc.strerror}.") from exc
    return info.st_size


def probe_argv(ffprobe: ToolInfo, path: Path) -> list[str]:
    """FFprobe arguments. The path is one argument, forced through the ``file:`` protocol
    so names like ``concat:a|b``, ``http://...`` or ``-x.mp4`` are never interpreted, and
    only the file protocol is allowed (no network or playlist fetches)."""
    return [
        *ffprobe.command,
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_error",
        "-i",
        f"file:{path}",
    ]


# -- running --------------------------------------------------------------------------


def probe_file(
    path: Path,
    ffprobe: ToolInfo,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Probe ``path`` and return a contract ``MediaProbe`` as a dict.

    Raises :class:`ProbeError`, or :class:`ProbeCancelled` if ``cancel`` is set.
    """
    if not ffprobe.ok:
        raise ProbeError(
            "tool.ffprobe_missing"
            if ffprobe.status == "missing"
            else f"tool.ffprobe_{ffprobe.status}",
            f"FFprobe is not usable: {ffprobe.problem}. "
            f"Install FFmpeg {MIN_FFMPEG_RELEASE} or newer, or set OWM_FFPROBE.",
            retryable=True,
        )
    size = precheck(path)
    # Keep the file's own path out of stderr tails, even outside the usual user dirs.
    redactor = Redactor([str(path)])
    try:
        result = run_tool(
            probe_argv(ffprobe, path),
            timeout_s=timeout_s,
            cancel=cancel,
            max_stdout=MAX_PROBE_OUTPUT,
            redactor=redactor,
        )
    except ToolCancelled as exc:
        raise ProbeCancelled from exc
    except ToolTimeout as exc:
        raise ProbeError(
            "media.probe_timeout",
            f"FFprobe did not finish within {timeout_s:g} seconds.",
            retryable=True,
            stderr_tail=exc.stderr_tail,
        ) from exc
    except ToolOutputTooLarge as exc:
        raise ProbeError(
            "media.probe_output_too_large",
            "FFprobe produced more metadata than allowed; the file is unusual or hostile.",
            stderr_tail=exc.stderr_tail,
        ) from exc
    except ToolNotStarted as exc:
        raise ProbeError("tool.ffprobe_unusable", str(exc), retryable=True) from exc

    try:
        data = json.loads(result.stdout or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProbeError(
            "media.probe_failed",
            "FFprobe returned unreadable output.",
            stderr_tail=result.stderr_tail,
        ) from exc
    if not isinstance(data, dict):
        data = {}
    if result.returncode != 0 or "error" in data:
        raise classify_failure(path, data.get("error"), result.stderr_tail)
    return normalize(data, size_bytes=size, ffprobe_version=ffprobe.version or "unknown")


class ProbeCancelled(Exception):
    """The probe was cancelled; FFprobe has been terminated."""


def classify_failure(path: Path, error: object, stderr_tail: str) -> ProbeError:
    """Map an FFprobe failure to a stable code: damaged (recognized but broken) vs unsupported."""
    code = error.get("code") if isinstance(error, dict) else None
    text = stderr_tail.lower()
    if isinstance(error, dict) and isinstance(error.get("string"), str):
        text += "\n" + error["string"].lower()
    details: dict[str, str | int | float | bool | None] = {}
    if isinstance(code, int):
        details["ffprobe_error"] = code
    if any(marker in text for marker in _DAMAGE_MARKERS):
        return ProbeError(
            "media.damaged",
            "The file looks like media but is damaged or incomplete (for example, a recording "
            "that was cut off). Re-export or copy it again from the console.",
            stderr_tail=stderr_tail,
            details={**details, "reason": "ffprobe_reported_damage"},
        )
    if code == AVERROR_INVALIDDATA and path.suffix.lower() in VIDEO_EXTENSIONS:
        return ProbeError(
            "media.damaged",
            f"The file has a {path.suffix.lower()} extension, "
            "but its contents are not readable media.",
            stderr_tail=stderr_tail,
            details={**details, "reason": "invalid_data_for_extension"},
        )
    if code == AVERROR_INVALIDDATA or "invalid data found" in text:
        return ProbeError(
            "media.unsupported_format",
            "The file is not in a media format FFprobe recognizes.",
            stderr_tail=stderr_tail,
            details=details,
        )
    return ProbeError(
        "media.probe_failed",
        "FFprobe could not read the file.",
        stderr_tail=stderr_tail,
        details=details,
    )


# -- normalization ----------------------------------------------------------------------


def normalize(data: Mapping[str, Any], *, size_bytes: int, ffprobe_version: str) -> dict[str, Any]:
    """Turn FFprobe ``-show_format -show_streams`` JSON into a validated ``MediaProbe``."""
    raw_format = data.get("format")
    fmt: Mapping[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    container = _text(fmt.get("format_name"))
    if not container:
        raise ProbeError("media.unsupported_format", "FFprobe did not report a container format.")
    if container in _STILL_FORMATS or container.endswith("_pipe"):
        raise ProbeError("media.still_image", "The file is a still image, not a video.")

    video_streams = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not _flag(s.get("disposition"), "attached_pic")
    ]
    if not video_streams:
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        raise ProbeError(
            "media.no_video_stream",
            "The file has no video stream" + (" (it is audio only)." if has_audio else "."),
            details={"audio_only": has_audio},
        )
    video_source = video_streams[0]
    video = _video(video_source)

    audio_sources = [s for s in streams if s.get("codec_type") == "audio"]
    audio = [a for a in (_audio(s) for s in audio_sources) if a is not None]
    other = len(streams) - 1 - len(audio)

    duration_ms = _duration_ms(fmt.get("duration")) or _duration_ms(video_source.get("duration"))
    if not duration_ms:
        raise ProbeError(
            "media.invalid_duration",
            "The file reports no duration; it may be incomplete or still being written.",
        )

    probe: dict[str, Any] = {
        "container": container[:200],
        "duration_ms": duration_ms,
        "size_bytes": size_bytes,
        "video": video,
        "audio": audio,
        "other_streams": max(0, other),
        "probed_with": {"ffprobe_version": ffprobe_version[:200]},
    }
    bit_rate = _int(fmt.get("bit_rate"))
    if bit_rate and bit_rate > 0:
        probe["bit_rate"] = bit_rate
    created = _utc(_tag(fmt, "creation_time")) or _utc(_tag(video_source, "creation_time"))
    if created:
        probe["creation_time"] = created
    # Contract validation is the last word on shape and ranges.
    return MediaProbe.model_validate(probe).model_dump(mode="json", exclude_none=True)


def _video(s: Mapping[str, Any]) -> dict[str, Any]:
    codec = _text(s.get("codec_name"))
    if not codec or codec == "none":
        raise ProbeError(
            "media.unsupported_codec",
            "The video codec is not recognized by this FFprobe build.",
            details={"codec_tag": _text(s.get("codec_tag_string")) or None},
        )
    width, height = _int(s.get("width")), _int(s.get("height"))
    if not width or not height or not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
        raise ProbeError(
            "media.invalid_dimensions",
            f"The video reports unusable dimensions ({width}x{height}).",
            details={"width": width, "height": height},
        )
    base = _rational(s.get("r_frame_rate"))
    average = _rational(s.get("avg_frame_rate"))
    if base is None and average is None:
        raise ProbeError("media.invalid_frame_rate", "The video reports no usable frame rate.")
    variable = False
    if base is not None and average is not None:
        variable = abs(base - average) / base > Fraction(1, 1000)
    nominal = base if (base is not None and not variable) else average
    if nominal is None:  # unreachable: one of the two is set
        raise ProbeError("media.invalid_frame_rate", "The video reports no usable frame rate.")
    video: dict[str, Any] = {
        "codec": codec[:64],
        "width": width,
        "height": height,
        "frame_rate": _rational_doc(nominal),
        "variable_frame_rate": variable,
        "rotation": _rotation(s),
        "color": _color(s),
    }
    if average is not None:
        video["average_frame_rate"] = _rational_doc(average)
    pix_fmt = _text(s.get("pix_fmt"))
    if pix_fmt:
        video["pixel_format"] = pix_fmt[:64]
    return video


def _audio(s: Mapping[str, Any]) -> dict[str, Any] | None:
    codec = _text(s.get("codec_name"))
    channels = _int(s.get("channels"))
    rate = _int(s.get("sample_rate"))
    if (
        not codec
        or not channels
        or not rate
        or not (1 <= channels <= 64 and 1000 <= rate <= 768000)
    ):
        return None  # an unusable audio stream is reported as 'other', not an error
    audio: dict[str, Any] = {"codec": codec[:64], "channels": channels, "sample_rate_hz": rate}
    layout = _text(s.get("channel_layout"))
    if layout:
        audio["channel_layout"] = layout[:64]
    return audio


def _color(s: Mapping[str, Any]) -> dict[str, Any]:
    color: dict[str, Any] = {}
    for key, source in (
        ("primaries", "color_primaries"),
        ("transfer", "color_transfer"),
        ("matrix", "color_space"),
        ("range", "color_range"),
    ):
        value = _text(s.get(source))
        if value:
            color[key] = value[: 64 if key != "range" else 16]
    for side in _side_data(s):
        kind = str(side.get("side_data_type", "")).lower()
        if kind.startswith("mastering display"):
            mastering = {
                k: v
                for k, v in (
                    ("min_luminance_nits", _nits(side.get("min_luminance"))),
                    ("max_luminance_nits", _nits(side.get("max_luminance"))),
                )
                if v is not None
            }
            if mastering:
                color["mastering_display"] = mastering
        elif kind.startswith("content light level"):
            max_cll, max_fall = _int(side.get("max_content")), _int(side.get("max_average"))
            if max_cll is not None and max_fall is not None and max_cll >= 0 and max_fall >= 0:
                color["content_light_level"] = {"max_cll": max_cll, "max_fall": max_fall}
        elif kind.startswith("dovi configuration"):
            profile = _int(side.get("dv_profile"))
            if profile is not None and 0 <= profile <= 31:
                dv: dict[str, int] = {"profile": profile}
                level = _int(side.get("dv_level"))
                if level is not None and 0 <= level <= 63:
                    dv["level"] = level
                color["dolby_vision"] = dv
    color["hdr"] = color.get("transfer") in HDR_TRANSFERS or "dolby_vision" in color
    return color


def _rotation(s: Mapping[str, Any]) -> int:
    """Clockwise degrees for upright display, snapped to a right angle.

    FFprobe's display-matrix ``rotation`` is counter-clockwise; the legacy
    ``rotate`` tag (older muxers) is clockwise.
    """
    for side in _side_data(s):
        value = _number(side.get("rotation"))
        if value is not None:
            return _snap(-value)
    legacy = _number(_tag(s, "rotate"))
    return _snap(legacy) if legacy is not None else 0


def _snap(degrees: float) -> int:
    return round(degrees / 90.0) % 4 * 90


# -- small parsers ------------------------------------------------------------------------


def _side_data(s: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = s.get("side_data_list")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _tag(s: Mapping[str, Any], name: str) -> Any:
    tags = s.get("tags")
    return tags.get(name) if isinstance(tags, dict) else None


def _flag(mapping: object, name: str) -> bool:
    return isinstance(mapping, dict) and mapping.get(name) in (1, "1", True)


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return "" if value in _UNKNOWN else value


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _rational(value: object) -> Fraction | None:
    """'30000/1001' → Fraction; '0/0', '0/1', and junk → None."""
    if not isinstance(value, str) or "/" not in value:
        return None
    num, _, den = value.partition("/")
    n, d = _int(num), _int(den)
    if not n or not d or n <= 0 or d <= 0:
        return None
    return Fraction(n, d)


def _rational_doc(value: Fraction) -> dict[str, int]:
    return {"num": value.numerator, "den": value.denominator}


def _nits(value: object) -> float | None:
    fraction = _rational(value) if isinstance(value, str) and "/" in value else None
    if fraction is not None:
        return float(fraction)
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _duration_ms(value: object) -> int | None:
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None
    try:
        seconds = Decimal(str(value))
    except InvalidOperation:
        return None
    if not seconds.is_finite() or seconds <= 0:
        return None
    return int((seconds * 1000).to_integral_value())


def _utc(value: object) -> str | None:
    """A container timestamp as contract UtcTimestamp (ms precision, 'Z'), or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)  # container times are UTC by convention
    moment = moment.astimezone(UTC)
    if moment.year < 1971:
        return None  # 1904/1970 epoch placeholders written by some muxers
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
