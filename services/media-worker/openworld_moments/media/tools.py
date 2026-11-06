# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discover FFprobe/FFmpeg and report what they can do.

Discovery order for each tool (first match wins):

1. an explicit path (worker ``--ffprobe`` / ``--ffmpeg`` flag),
2. the ``OWM_FFPROBE`` / ``OWM_FFMPEG`` environment variable,
3. ``PATH``.

A tool is usable when ``<tool> -version`` runs and its libavformat and
libavcodec majors are at least :data:`MIN_LIBRARIES` (FFmpeg 6.0). The library
versions are checked rather than the release string because Git and distro
builds report versions like ``N-118000-g1a2b3c`` or ``6.1.1-3ubuntu5``.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from openworld_moments.media.process import ToolError, run_tool

#: Minimum library majors: FFmpeg 6.0 (libavformat 60, libavcodec 60).
MIN_LIBRARIES: Mapping[str, int] = {"libavformat": 60, "libavcodec": 60}
MIN_FFMPEG_RELEASE = "6.0"
ENV_VARS: Mapping[str, str] = {"ffprobe": "OWM_FFPROBE", "ffmpeg": "OWM_FFMPEG"}
VERSION_TIMEOUT_S = 10.0
LIST_TIMEOUT_S = 15.0

#: Decoders and encoders reported by ``doctor``; none is required to probe.
DECODERS = ("h264", "hevc", "av1", "vp9", "aac", "opus")
ENCODERS = ("libx264", "libx265", "aac")
#: What derived media (M08: proxies, thumbnails, waveforms) needs from FFmpeg.
DERIVED_ENCODERS = ("libx264", "aac", "mjpeg", "pcm_s16le")
DERIVED_FILTERS = ("scale", "format", "setparams", "lut3d", "fps")

ToolName = Literal["ffprobe", "ffmpeg"]
Status = Literal["ok", "missing", "too_old", "unusable"]

_VERSION_LINE = re.compile(r"^(?:ffprobe|ffmpeg) version (\S+)", re.MULTILINE)
_LIBRARY_LINE = re.compile(r"^\s*(lib[a-z]+)\s+(\d+)\.\s*(\d+)\.\s*(\d+)", re.MULTILINE)
_CODEC_LINE = re.compile(r"^\s[A-Z.]{6}\s+(\S+)", re.MULTILINE)
# " TS colorspace        V->V       Convert ..." (2 or 3 flag columns by version).
_FILTER_LINE = re.compile(r"^\s*[TSC.]{2,3}\s+(\S+)\s+\S*->\S*", re.MULTILINE)


@dataclass(frozen=True)
class ToolInfo:
    """A located, version-checked tool. ``command`` is the argv prefix to run it."""

    name: ToolName
    command: tuple[str, ...]
    source: Literal["flag", "env", "path", "test"]
    status: Status
    version: str | None = None
    libraries: Mapping[str, str] = field(default_factory=dict)
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def path(self) -> str:
        return self.command[0] if self.command else ""

    def report(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "source": self.source}
        if self.command:
            out["path"] = self.path
        if self.version:
            out["version"] = self.version
        if self.libraries:
            out["libraries"] = dict(self.libraries)
        if self.problem:
            out["problem"] = self.problem
        return out


def parse_version_output(text: str) -> tuple[str | None, dict[str, str]]:
    """Release string and ``{library: 'major.minor.micro'}`` from ``-version`` output."""
    match = _VERSION_LINE.search(text)
    version = match.group(1) if match else None
    if version and version.startswith("n") and version[1:2].isdigit():
        version = version[1:]  # Git tag builds: 'n7.1'
    libraries = {
        m.group(1): f"{m.group(2)}.{m.group(3)}.{m.group(4)}" for m in _LIBRARY_LINE.finditer(text)
    }
    return version, libraries


def check_libraries(libraries: Mapping[str, str]) -> str | None:
    """A problem description when a required library is missing or too old."""
    for library, minimum in MIN_LIBRARIES.items():
        found = libraries.get(library)
        if found is None:
            return f"{library} version not reported"
        if int(found.split(".")[0]) < minimum:
            return f"{library} {found} is older than {minimum} (FFmpeg {MIN_FFMPEG_RELEASE})"
    return None


def _locate(
    name: ToolName, explicit: str | None
) -> tuple[str | None, Literal["flag", "env", "path"]]:
    if explicit:
        return explicit, "flag"
    env = os.environ.get(ENV_VARS[name])
    if env:
        return env, "env"
    return shutil.which(name), "path"


def inspect_tool(name: ToolName, explicit: str | None = None) -> ToolInfo:
    """Locate ``name`` and check its version. Never raises."""
    location, source = _locate(name, explicit)
    if not location:
        return ToolInfo(name, (), source, "missing", problem=f"{name} was not found on PATH")
    if not Path(location).is_file():
        return ToolInfo(
            name, (location,), source, "missing", problem=f"{name} not found at the configured path"
        )
    return check_command(name, (location,), source)


def check_command(
    name: ToolName, command: tuple[str, ...], source: Literal["flag", "env", "path", "test"]
) -> ToolInfo:
    try:
        result = run_tool([*command, "-hide_banner", "-version"], timeout_s=VERSION_TIMEOUT_S)
    except ToolError as exc:
        return ToolInfo(name, command, source, "unusable", problem=str(exc))
    text = result.stdout.decode("utf-8", errors="replace")
    version, libraries = parse_version_output(text)
    if result.returncode != 0 or version is None:
        return ToolInfo(name, command, source, "unusable", problem=f"`{name} -version` failed")
    problem = check_libraries(libraries)
    status: Status = "too_old" if problem else "ok"
    return ToolInfo(name, command, source, status, version, libraries, problem)


def list_codecs(tool: ToolInfo, kind: Literal["decoders", "encoders"]) -> set[str]:
    """Names from ``-decoders`` / ``-encoders``; empty when the tool is unusable."""
    if not tool.ok:
        return set()
    try:
        result = run_tool([*tool.command, "-hide_banner", f"-{kind}"], timeout_s=LIST_TIMEOUT_S)
    except ToolError:
        return set()
    if result.returncode != 0:
        return set()
    return set(_CODEC_LINE.findall(result.stdout.decode("utf-8", errors="replace")))


def list_filters(tool: ToolInfo) -> set[str]:
    """Filter names from ``-filters``; empty when the tool is unusable."""
    if not tool.ok:
        return set()
    try:
        result = run_tool([*tool.command, "-hide_banner", "-filters"], timeout_s=LIST_TIMEOUT_S)
    except ToolError:
        return set()
    if result.returncode != 0:
        return set()
    return set(_FILTER_LINE.findall(result.stdout.decode("utf-8", errors="replace")))


class MediaTools:
    """Thread-safe cache of the located tools and their capability report."""

    def __init__(self, ffprobe: str | None = None, ffmpeg: str | None = None) -> None:
        self._explicit: dict[ToolName, str | None] = {"ffprobe": ffprobe, "ffmpeg": ffmpeg}
        self._lock = threading.Lock()
        self._tools: dict[ToolName, ToolInfo] = {}
        self._report: dict[str, Any] | None = None

    def tool(self, name: ToolName) -> ToolInfo:
        """The located tool. A tool that is not ``ok`` is checked again on the next call,
        so installing FFmpeg does not require restarting the worker."""
        with self._lock:
            cached = self._tools.get(name)
            if cached is not None and cached.ok:
                return cached
        info = inspect_tool(name, self._explicit[name])
        with self._lock:
            self._tools[name] = info
            if not info.ok:
                self._report = None
        return info

    def capabilities(self, *, refresh: bool = False) -> dict[str, Any]:
        """The capability report served by ``/v1/capabilities`` and ``doctor``."""
        with self._lock:
            if refresh:
                self._tools.clear()
                self._report = None
            if self._report is not None:
                return self._report
        ffprobe = self.tool("ffprobe")
        ffmpeg = self.tool("ffmpeg")
        decoders = list_codecs(ffprobe, "decoders")
        encoders = list_codecs(ffmpeg, "encoders")
        filters = list_filters(ffmpeg)
        derived_missing = [f"encoder:{e}" for e in DERIVED_ENCODERS if e not in encoders]
        derived_missing += [f"filter:{f}" for f in DERIVED_FILTERS if f not in filters]
        report: dict[str, Any] = {
            "probe_ready": ffprobe.ok,
            "minimum": {"ffmpeg_release": MIN_FFMPEG_RELEASE, **MIN_LIBRARIES},
            "ffprobe": ffprobe.report(),
            "ffmpeg": ffmpeg.report(),
            "decoders": {name: name in decoders for name in DECODERS},
            "encoders": {name: name in encoders for name in ENCODERS},
            "derived": {
                "ready": ffprobe.ok and ffmpeg.ok and not derived_missing,
                "missing": derived_missing if ffmpeg.ok else ["ffmpeg"],
            },
        }
        with self._lock:
            if ffprobe.ok and ffmpeg.ok:
                self._report = report  # cache only a fully healthy report
        return report
