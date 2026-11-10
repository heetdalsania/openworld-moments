# SPDX-License-Identifier: AGPL-3.0-or-later
"""First-run doctor: bounded local checks, no footage, external network or model downloads."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from openworld_moments import __version__
from openworld_moments.media.tools import MediaTools
from openworld_moments.render.encoders import EncoderProbe
from openworld_moments.transcripts.catalog import read_catalog
from openworld_moments.transcripts.whisper import TranscriptionError, sha256_file


def inventory(root: Path) -> dict[str, Any]:
    path = root / "inventory.json"
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError("inventory")
    doc: dict[str, Any] = json.loads(path.read_text("utf-8"))
    for name, digest in doc["files"].items():
        relative = Path(name)
        target = root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not target.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("path")
        if target.is_symlink() or not target.is_file() or sha256_file(target) != digest:
            raise ValueError("checksum")
    for required in ("owm-worker.exe", "tools/ffmpeg.exe", "tools/ffprobe.exe"):
        if required not in doc["files"]:
            raise ValueError("incomplete")
    return doc


def configure_bundle() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = Path(sys.executable).resolve().parent
    inventory(root)
    os.environ["OWM_FFMPEG"] = str(root / "tools" / "ffmpeg.exe")
    os.environ["OWM_FFPROBE"] = str(root / "tools" / "ffprobe.exe")


def doctor(library: Path, tools: MediaTools) -> dict[str, Any]:
    packaged = bool(getattr(sys, "frozen", False))
    checks: list[dict[str, str]] = []

    def add(name: str, good: bool, message: str, *, optional: bool = False) -> None:
        checks.append(
            {
                "id": name,
                "status": "pass" if good else "warn" if optional else "fail",
                "message": message,
            }
        )

    library.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(library).free
    add(
        "storage",
        free >= 512 * 1024**2,
        "Keep at least 512 MiB free; imports, models and renders need additional space.",
    )
    try:
        with tempfile.TemporaryFile(dir=library) as stream:
            stream.write(b"owm-system-check")
            stream.flush()
        writable = True
    except OSError:
        writable = False
    add(
        "permissions",
        writable,
        "The library must allow temporary files. Choose a writable local folder if this fails.",
    )
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
        ports = True
    except OSError:
        ports = False
    add(
        "loopback",
        ports,
        "Allow local loopback ports in security software. Phone LAN is off by default.",
    )
    with sqlite3.connect(":memory:") as conn:
        try:
            conn.execute("CREATE VIRTUAL TABLE doctor USING fts5(text)")
            fts = sqlite3.sqlite_version_info >= (3, 42, 0)
        except sqlite3.Error:
            fts = False
    add(
        "sqlite",
        fts,
        "SQLite 3.42 or newer with FTS5 is required. Repair the bundled runtime if unavailable.",
    )
    caps = tools.capabilities()
    add(
        "codecs",
        bool(caps.get("probe_ready") and caps.get("derived", {}).get("ready")),
        "FFmpeg needs libx264, AAC, JPEG and proxy filters. Repair packaged tools if missing.",
    )
    try:
        encoders = EncoderProbe().status(tools.tool("ffmpeg"))
        hardware = any(e.get("available") and e.get("kind") == "hardware" for e in encoders)
        cpu = any(e.get("available") and e.get("id") == "libx264" for e in encoders)
    except (KeyError, TypeError, AttributeError):
        hardware = False
        cpu = False
    add("cpu-encode", cpu, "The CPU test encode must pass. Repair packaged tools if it fails.")
    add(
        "acceleration",
        hardware,
        "Hardware needs a test encode. CPU libx264 is the fallback when unavailable.",
        optional=True,
    )
    try:
        read_catalog()
        signed = True
    except TranscriptionError:
        signed = False
    add(
        "models",
        signed,
        "Catalog signature required. Repair the app on failure. Downloads are explicit.",
    )
    runtimes: list[dict[str, Any]] = [
        {
            "name": "Python",
            "version": platform.python_version(),
            "origin": "bundle" if packaged else "development",
            "license": "PSF-2.0",
        },
        {
            "name": "SQLite",
            "version": sqlite3.sqlite_version,
            "origin": "bundle" if packaged else "development",
            "license": "blessing",
        },
        {
            "name": "Worker",
            "version": __version__,
            "origin": "bundle" if packaged else "development",
            "license": "AGPL-3.0-or-later",
        },
    ]
    if packaged:
        try:
            doc = inventory(Path(sys.executable).resolve().parent)
            runtimes[2]["sha256"] = doc["files"]["owm-worker.exe"]
            runtimes[2]["version"] += " / " + doc["commit"][:12]
            runtimes.extend(doc["tools"])
            verified = True
        except (OSError, ValueError, KeyError, TypeError):
            verified = False
        add(
            "inventory",
            verified,
            "Packaged runtime checksums must match. Repair the application on mismatch.",
        )
    else:
        for name in ("ffmpeg", "ffprobe"):
            runtimes.append(
                {
                    "name": name,
                    "version": caps[name].get("version", "unavailable"),
                    "origin": "development",
                    "license": "Build dependent; not a packaged runtime",
                }
            )
        add(
            "development",
            False,
            "Development runtime; Windows installer qualification is separate.",
            optional=True,
        )
    return {
        "schema_version": "1.23",
        "ready": not any(c["status"] == "fail" for c in checks),
        "packaged": packaged,
        "platform": platform.system(),
        "architecture": platform.machine(),
        "free_bytes": free,
        "checks": checks,
        "tools": runtimes,
    }
