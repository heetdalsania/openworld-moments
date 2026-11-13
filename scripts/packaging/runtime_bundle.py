# SPDX-License-Identifier: AGPL-3.0-or-later
"""Steps shared by the Windows (M29) and macOS (M34) worker freezes.

Moved unchanged from `scripts/windows/freeze-worker.py` so both platforms freeze,
canonicalize, collect notices and inventory the runtime the same way.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "packaging"
DEST = ROOT / "apps/desktop/src-tauri/bundle-input/runtime"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonicalize_stdlib_zip(path: Path) -> dict[str, str]:
    """PyInstaller's module set order varies; preserve bytes, sort the ZIP container."""
    with zipfile.ZipFile(path) as source:
        entries = [(entry.filename, source.read(entry)) for entry in source.infolist()]
    if len({name for name, _ in entries}) != len(entries):
        raise ValueError("Duplicate standard-library ZIP member")
    temporary = path.with_suffix(".canonical.zip")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as target:
        for name, content in sorted(entries):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            target.writestr(entry, content)
    os.replace(temporary, path)
    return {name: hashlib.sha256(content).hexdigest() for name, content in sorted(entries)}


def pyinstaller_args(environment_python: str, name: str = "owm-worker") -> list[str]:
    """The PyInstaller command line: a console onedir worker (pipes are the protocol)."""
    return [
        environment_python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        name,
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


def freeze_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    environment["SOURCE_DATE_EPOCH"] = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    return environment


def copy_data_and_licenses() -> Path:
    """Profiles, presets and the repository licenses; returns the notices folder."""
    for name in ("profiles", "presets"):
        shutil.copytree(ROOT / name, DEST / "data" / name)
    notices = DEST / "notices"
    notices.mkdir()
    for file in (ROOT / "LICENSES").iterdir():
        shutil.copyfile(file, notices / file.name)
    return notices


def python_package_notices(notices: Path) -> None:
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


def javascript_notices(notices: Path) -> dict[str, dict[str, Any]]:
    javascript: dict[str, dict[str, Any]] = {}
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
    return javascript


def python_runtime_notices(notices: Path, python_license: Path) -> dict[str, Any]:
    """The CPython license and the pinned, hash-checked python-build-standalone notices."""
    if not python_license.is_file():
        raise RuntimeError("Python runtime license not found")
    shutil.copyfile(python_license, notices / "Python-LICENSE.txt")
    python_notices: dict[str, Any] = json.loads(
        (ROOT / "scripts/windows/python-notices.json").read_text()
    )
    notice_cache = OUT / "python-notices"
    notice_cache.mkdir(exist_ok=True)
    python_target = notices / "python-runtime"
    python_target.mkdir()
    for name, source in python_notices["files"].items():
        if Path(name).name != name:
            raise ValueError("Invalid notice filename")
        cached = notice_cache / name
        if not cached.exists():
            with urllib.request.urlopen(source["url"], timeout=30) as response:  # noqa: S310
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Runtime notice exceeds limit")
            cached.write_bytes(raw)
        if digest(cached) != source["sha256"]:
            raise ValueError("Runtime notice checksum mismatch")
        shutil.copyfile(cached, python_target / name)
    return python_notices


def rust_notices(notices: Path) -> None:
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


def media_notices(notices: Path) -> None:
    shutil.copyfile(OUT / "source-build/ffmpeg/COPYING.GPLv2", notices / "FFmpeg-GPLv2.txt")
    shutil.copyfile(OUT / "source-build/x264/COPYING", notices / "x264-COPYING.txt")


def file_hashes() -> dict[str, str]:
    return {
        p.relative_to(DEST).as_posix(): digest(p) for p in sorted(DEST.rglob("*")) if p.is_file()
    }


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def write_inventory(metadata: dict[str, Any], notices_text: str) -> None:
    """Write inventory.json, then THIRD_PARTY_NOTICES.txt, then re-write the inventory
    with the notices file's hash (the inventory cannot list its own hash)."""
    (DEST / "inventory.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (OUT / "THIRD_PARTY_NOTICES.txt").write_text(notices_text, encoding="utf-8")
    shutil.copyfile(OUT / "THIRD_PARTY_NOTICES.txt", DEST / "THIRD_PARTY_NOTICES.txt")
    metadata["files"]["THIRD_PARTY_NOTICES.txt"] = digest(DEST / "THIRD_PARTY_NOTICES.txt")
    (DEST / "inventory.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
