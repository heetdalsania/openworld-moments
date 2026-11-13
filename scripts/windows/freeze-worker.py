# SPDX-License-Identifier: AGPL-3.0-or-later
"""Freeze a console worker (its pipes are the supervisor protocol), then inventory it.

The steps shared with the macOS freeze (M34) live in scripts/packaging/runtime_bundle.py.
"""

import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))

from build_paths import redact  # noqa: E402
from runtime_bundle import (  # noqa: E402
    DEST,
    OUT,
    ROOT,
    canonicalize_stdlib_zip,
    copy_data_and_licenses,
    digest,
    file_hashes,
    freeze_environment,
    git_commit,
    javascript_notices,
    media_notices,
    pyinstaller_args,
    python_package_notices,
    python_runtime_notices,
    rust_notices,
    write_inventory,
)


def main() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Build the Windows x64 worker on native Windows x64")
    if sys.version_info[:3] != (3, 12, 14):
        raise RuntimeError("Packaging pins Python 3.12.14")
    subprocess.run(pyinstaller_args(sys.executable), cwd=ROOT, env=freeze_environment(), check=True)
    frozen = OUT / "frozen/owm-worker"
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(frozen, DEST)
    stdlib_modules = canonicalize_stdlib_zip(DEST / "_internal/base_library.zip")
    for file in DEST.rglob("direct_url.json"):
        file.unlink()  # editable-build locations are not release metadata
    (DEST / "tools").mkdir()
    for name in ("ffmpeg", "ffprobe"):
        shutil.copyfile(OUT / f"media/{name}.exe", DEST / f"tools/{name}.exe")
    notices = copy_data_and_licenses()
    python_package_notices(notices)
    shutil.copytree(OUT / "media/toolchain-notices", notices / "mingw-toolchain")
    javascript = javascript_notices(notices)
    python_notices = python_runtime_notices(notices, Path(sys.base_prefix) / "LICENSE.txt")
    sources = json_sources()
    media_notices(notices)
    tools = []
    media_build = {}
    for name in ("ffmpeg", "ffprobe"):
        output = subprocess.check_output(
            [str(DEST / f"tools/{name}.exe"), "-version"], text=True, encoding="utf-8"
        )
        # The configure line names the CI workspace; ship it without absolute paths (M30).
        media_build[name] = redact(output)
        if "--enable-gpl" not in output or "--enable-nonfree" in output:
            raise RuntimeError("Unexpected FFmpeg licensing configuration")
        tools.append(
            {
                "name": name,
                "version": output.splitlines()[0],
                "origin": "bundle",
                "license": "GPL-2.0-or-later",
                "sha256": digest(DEST / f"tools/{name}.exe"),
                "architecture": "x86_64",
            }
        )
    for path in DEST.rglob("*"):
        if path.suffix.lower() in {".exe", ".dll", ".pyd"}:
            raw = path.read_bytes()
            pe = struct.unpack_from("<I", raw, 0x3C)[0]
            if raw[pe : pe + 4] != b"PE\0\0" or struct.unpack_from("<H", raw, pe + 4)[0] != 0x8664:
                raise RuntimeError("Wrong native architecture: " + path.name)
    rust_notices(notices)
    metadata = {
        "format_version": 1,
        "application": "0.1.0-alpha.29",
        "python": "3.12.14",
        "pyinstaller": "6.22.3",
        "uv": "0.13.7",
        "python_build": "20260929",
        "python_notices": python_notices,
        "javascript_packages": [javascript[key] for key in sorted(javascript)],
        "stdlib_modules": stdlib_modules,
        "architecture": "x86_64",
        "sources": sources,
        "commit": git_commit(),
        "files": file_hashes(),
        "tools": tools,
        "media_build": media_build,
    }
    write_inventory(
        metadata,
        "OpenWorld Moments Windows alpha: AGPL-3.0-or-later.\n"
        "FFmpeg and x264: GPL-2.0-or-later; matching source archives accompany this artifact.\n"
        "Python: PSF-2.0. Runtime and JavaScript package license texts are in runtime/notices.\n"
        "WebView2: Microsoft-managed Windows component; not bundled or frozen.\n"
        "No OCR engine, whisper.cpp engine or model weights are bundled.\n"
        "Runtime inventory and exact sources: runtime/inventory.json.\n",
    )


def json_sources() -> dict[str, object]:
    import json

    sources: dict[str, object] = json.loads((ROOT / "scripts/windows/sources.json").read_text())
    return sources


if __name__ == "__main__":
    main()
