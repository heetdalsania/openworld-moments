# SPDX-License-Identifier: AGPL-3.0-or-later
"""Freeze the macOS worker for this Mac's architecture and inventory the runtime (M34).

Same strategy as Windows (M29): PyInstaller 6.22.3 console onedir on the pinned
python-build-standalone CPython 3.12.14 through uv 0.13.7, with the steps shared in
scripts/packaging/runtime_bundle.py. Run on a native Mac of the target architecture:

    uv sync --managed-python --locked --all-packages --no-dev --group packaging \
        --python cpython-3.12.14-macos-<aarch64|x86_64>-none
    bash scripts/macos/build-media.sh <arm64|x86_64>
    uv run --locked --no-dev --group packaging --directory services/media-worker \
        python ../../scripts/macos/freeze-worker.py

The result is `apps/desktop/src-tauri/bundle-input/runtime/` (ignored by Git), which the
macOS build bundles as `Contents/Resources/runtime/`. Every Mach-O file must be a thin
binary of this architecture that runs on macOS 14 and links only system libraries or
files inside the runtime.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))

from build_paths import redact  # noqa: E402
from macho import audit_runtime  # noqa: E402
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

FLOOR = "14.0"
ARCH = {"arm64": "arm64", "x86_64": "x86_64"}


def main() -> None:
    arch = platform.machine()
    if sys.platform != "darwin" or arch not in ARCH:
        raise RuntimeError("Build the macOS worker on a native Apple Silicon or Intel Mac")
    if sys.version_info[:3] != (3, 12, 14):
        raise RuntimeError("Packaging pins Python 3.12.14")
    # A Homebrew or system Python targets the build Mac's macOS release and links
    # outside itself; the Mach-O audit below rejects it (minimum above 14.0 or a
    # dependency outside the runtime), so only the standalone build passes.
    subprocess.run(pyinstaller_args(sys.executable), cwd=ROOT, env=freeze_environment(), check=True)
    frozen = OUT / "frozen/owm-worker"
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(frozen, DEST, symlinks=True)
    stdlib_modules = canonicalize_stdlib_zip(DEST / "_internal/base_library.zip")
    for file in DEST.rglob("direct_url.json"):
        file.unlink()  # editable-build locations are not release metadata
    (DEST / "tools").mkdir()
    for name in ("ffmpeg", "ffprobe"):
        shutil.copyfile(OUT / f"media/{name}", DEST / f"tools/{name}")
        (DEST / f"tools/{name}").chmod(0o755)
    notices = copy_data_and_licenses()
    python_package_notices(notices)
    javascript = javascript_notices(notices)
    python_license = Path(sys.base_prefix) / "lib/python3.12/LICENSE.txt"
    python_notices = python_runtime_notices(notices, python_license)
    sources = json_sources()
    media_notices(notices)
    tools = []
    media_build = {}
    for name in ("ffmpeg", "ffprobe"):
        output = subprocess.check_output(
            [str(DEST / f"tools/{name}"), "-version"], text=True, encoding="utf-8"
        )
        media_build[name] = redact(output)
        if "--enable-gpl" not in output or "--enable-nonfree" in output:
            raise RuntimeError("Unexpected FFmpeg licensing configuration")
        tools.append(
            {
                "name": name,
                "version": output.splitlines()[0],
                "origin": "bundle",
                "license": "GPL-2.0-or-later",
                "sha256": digest(DEST / f"tools/{name}"),
                "architecture": ARCH[arch],
            }
        )
    problems, audit = audit_runtime(DEST, ARCH[arch], FLOOR)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        raise RuntimeError(f"{len(problems)} Mach-O problems in the runtime")
    rust_notices(notices)
    metadata = {
        "format_version": 1,
        "platform": "macos",
        "application": "0.1.0-alpha.34",
        "python": "3.12.14",
        "pyinstaller": "6.22.3",
        "uv": "0.13.7",
        "python_build": "20260929",
        "python_notices": python_notices,
        "javascript_packages": [javascript[key] for key in sorted(javascript)],
        "stdlib_modules": stdlib_modules,
        "architecture": ARCH[arch],
        "minimum_macos": FLOOR,
        "sources": sources,
        "commit": git_commit(),
        "files": file_hashes(),
        "tools": tools,
        "media_build": media_build,
        "macho_audit": audit,
    }
    write_inventory(
        metadata,
        f"OpenWorld Moments macOS ({ARCH[arch]}) development build: AGPL-3.0-or-later.\n"
        "FFmpeg and x264: GPL-2.0-or-later; matching source archives accompany release builds.\n"
        "Python: PSF-2.0. Runtime and JavaScript package license texts are in runtime/notices.\n"
        "WebKit (WKWebView): Apple-managed macOS component; not bundled.\n"
        "No OCR engine, whisper.cpp engine or model weights are bundled.\n"
        "Runtime inventory and exact sources: runtime/inventory.json.\n",
    )
    print(f"froze the {ARCH[arch]} worker: {len(metadata['files'])} files")  # type: ignore[arg-type]


def json_sources() -> dict[str, object]:
    import json

    sources: dict[str, object] = json.loads((ROOT / "scripts/windows/sources.json").read_text())
    return sources


if __name__ == "__main__":
    main()
