# SPDX-License-Identifier: AGPL-3.0-or-later
"""Freeze a console worker (its pipes are the supervisor protocol), then inventory it."""

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "packaging"
DEST = ROOT / "apps/desktop/src-tauri/bundle-input/runtime"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Build the Windows x64 worker on native Windows x64")
    if sys.version_info[:3] != (3, 12, 14):
        raise RuntimeError("Packaging pins Python 3.12.14")
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    environment["SOURCE_DATE_EPOCH"] = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        "owm-worker",
        "--distpath",
        str(OUT / "frozen"),
        "--workpath",
        str(OUT / "freeze-work"),
        "--specpath",
        str(OUT),
        "--collect-all",
        "openworld_moments_contracts",
        "--collect-all",
        "openworld_moments",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "websockets",
        "--exclude-module",
        "cv2",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "pytest",
        str(ROOT / "services/media-worker/openworld_moments/frozen.py"),
    ]
    subprocess.run(args, cwd=ROOT, env=environment, check=True)
    frozen = OUT / "frozen/owm-worker"
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(frozen, DEST)
    for file in DEST.rglob("direct_url.json"):
        file.unlink()  # editable-build locations are not release metadata
    (DEST / "tools").mkdir()
    for name in ("ffmpeg", "ffprobe"):
        shutil.copyfile(OUT / f"media/{name}.exe", DEST / f"tools/{name}.exe")
    for name in ("profiles", "presets"):
        shutil.copytree(ROOT / name, DEST / "data" / name)
    notices = DEST / "notices"
    notices.mkdir()
    for file in (ROOT / "LICENSES").iterdir():
        shutil.copyfile(file, notices / file.name)
    for dist in importlib.metadata.distributions():
        for file in dist.files or []:
            if ".dist-info" in str(file) and any(
                term in str(file).lower() for term in ("license", "copying", "notice")
            ):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    folder = notices / (dist.metadata["Name"] + "-" + dist.version)
                    folder.mkdir(exist_ok=True)
                    shutil.copyfile(source, folder / source.name)
    shutil.copytree(OUT / "media/toolchain-notices", notices / "mingw-toolchain")
    javascript = {}
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("Pinned pnpm installation is required")
    for workspace in ("@openworld-moments/desktop", "@openworld-moments/contracts"):
        licenses = json.loads(
            subprocess.check_output(
                [pnpm, "--filter", workspace, "licenses", "list", "--prod", "--json"],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
            )
        )
        for packages in licenses.values():
            for package in packages:
                key = (
                    re.sub(r"[^A-Za-z0-9._-]", "_", package["name"])
                    + "-"
                    + "-".join(package["versions"])
                )
                target = notices / ("javascript-" + key)
                target.mkdir(exist_ok=True)
                found = False
                for folder in package["paths"]:
                    for source in Path(folder).iterdir():
                        if (
                            source.name.lower().startswith(
                                ("license", "licence", "copying", "notice")
                            )
                            and source.is_file()
                            and source.resolve().is_relative_to(ROOT.resolve())
                        ):
                            shutil.copyfile(source, target / source.name)
                            found = True
                if not found:
                    raise RuntimeError("Missing JavaScript package notices: " + package["name"])
                javascript[key] = {
                    field: package[field] for field in ("name", "versions", "license")
                }
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python runtime license not found")
    shutil.copyfile(python_license, notices / "Python-LICENSE.txt")
    python_notices = json.loads((ROOT / "scripts/windows/python-notices.json").read_text())
    notice_cache = OUT / "python-notices"
    notice_cache.mkdir(exist_ok=True)
    python_target = notices / "python-runtime"
    python_target.mkdir()
    for name, source in python_notices["files"].items():
        if Path(name).name != name:
            raise ValueError("Invalid notice filename")
        cached = notice_cache / name
        if not cached.exists():
            with urllib.request.urlopen(source["url"], timeout=30) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Runtime notice exceeds limit")
            cached.write_bytes(raw)
        if digest(cached) != source["sha256"]:
            raise ValueError("Runtime notice checksum mismatch")
        shutil.copyfile(cached, python_target / name)
    sources = json.loads((ROOT / "scripts/windows/sources.json").read_text())
    shutil.copyfile(OUT / "source-build/ffmpeg/COPYING.GPLv2", notices / "FFmpeg-GPLv2.txt")
    shutil.copyfile(OUT / "source-build/x264/COPYING", notices / "x264-COPYING.txt")
    tools = []
    media_build = {}
    for name in ("ffmpeg", "ffprobe"):
        output = subprocess.check_output(
            [str(DEST / f"tools/{name}.exe"), "-version"], text=True, encoding="utf-8"
        )
        media_build[name] = output
        if "--enable-gpl" not in output or "--enable-nonfree" in output:
            raise RuntimeError("Unexpected FFmpeg licensing configuration")
        tools.append(
            {
                "name": name,
                "version": output.splitlines()[0],
                "origin": "bundle",
                "license": "GPL-2.0-or-later",
                "sha256": digest(DEST / f"tools/{name}.exe"),
            }
        )
    for path in DEST.rglob("*"):
        if path.suffix.lower() in {".exe", ".dll", ".pyd"}:
            raw = path.read_bytes()
            pe = struct.unpack_from("<I", raw, 0x3C)[0]
            if raw[pe : pe + 4] != b"PE\0\0" or struct.unpack_from("<H", raw, pe + 4)[0] != 0x8664:
                raise RuntimeError("Wrong native architecture: " + path.name)
    cargo = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--format-version", "1"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
    )
    for package in cargo["packages"]:
        folder = Path(package["manifest_path"]).parent
        license_files = set()
        for pattern in ("LICENSE*", "LICENCE*", "COPYING*", "NOTICE*"):
            license_files.update(folder.glob(pattern))
        if package.get("license_file"):
            license_files.add(folder / package["license_file"])
        for source in sorted(license_files):
            if source.is_file() and source.resolve().is_relative_to(folder.resolve()):
                target = notices / ("rust-" + package["name"] + "-" + package["version"])
                target.mkdir(exist_ok=True)
                shutil.copyfile(source, target / source.name)
    files = {
        p.relative_to(DEST).as_posix(): digest(p) for p in sorted(DEST.rglob("*")) if p.is_file()
    }
    metadata = {
        "format_version": 1,
        "application": "0.1.0-alpha.29",
        "python": "3.12.14",
        "pyinstaller": "6.22.3",
        "uv": "0.13.7",
        "python_build": "20260929",
        "python_notices": python_notices,
        "javascript_packages": [javascript[key] for key in sorted(javascript)],
        "architecture": "x86_64",
        "sources": sources,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "files": files,
        "tools": tools,
        "media_build": media_build,
    }
    (DEST / "inventory.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (OUT / "THIRD_PARTY_NOTICES.txt").write_text(
        "OpenWorld Moments Windows alpha: AGPL-3.0-or-later.\n"
        "FFmpeg and x264: GPL-2.0-or-later; matching source archives accompany this artifact.\n"
        "Python: PSF-2.0. Runtime and JavaScript package license texts are in runtime/notices.\n"
        "WebView2: Microsoft-managed Windows component; not bundled or frozen.\n"
        "No OCR engine, whisper.cpp engine or model weights are bundled.\n"
        "Runtime inventory and exact sources: runtime/inventory.json.\n",
        encoding="utf-8",
    )
    shutil.copyfile(OUT / "THIRD_PARTY_NOTICES.txt", DEST / "THIRD_PARTY_NOTICES.txt")
    metadata["files"]["THIRD_PARTY_NOTICES.txt"] = digest(DEST / "THIRD_PARTY_NOTICES.txt")
    (DEST / "inventory.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
