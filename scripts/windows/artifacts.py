# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble auditable Actions assets, never publish a release or include synthetic media."""

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/packaging"
RUNTIME = ROOT / "apps/desktop/src-tauri/bundle-input/runtime"


def main() -> None:
    release = OUT / "release"
    if release.is_symlink():
        raise ValueError("Refusing a linked artifact directory")
    if release.exists():
        shutil.rmtree(release)
    release.mkdir()
    installers = list(
        (ROOT / "target/x86_64-pc-windows-msvc/release/bundle/nsis").glob("*alpha.29_*-setup.exe")
    )
    if len(installers) != 1:
        raise RuntimeError("Expected exactly one M29 alpha installer")
    shutil.copyfile(
        installers[0], release / "OpenWorld-Moments_0.1.0-alpha.29_Windows_x64-setup.exe"
    )
    for path in (OUT / "sources").iterdir():
        shutil.copyfile(path, release / path.name)
    for path in (
        "THIRD_PARTY_NOTICES.txt",
        "reproducibility.json",
        "native-import-render.json",
        "native-repair.json",
        "native-upgrade.json",
        "native-uninstall.json",
    ):
        shutil.copyfile(OUT / path, release / path)
    shutil.copyfile(RUNTIME / "inventory.json", release / "runtime-inventory.json")
    shutil.make_archive(str(release / "runtime-notices"), "zip", RUNTIME / "notices")
    for path in ("build-media.sh", "freeze-worker.py", "sources.json", "python-notices.json"):
        shutil.copyfile(ROOT / "scripts/windows" / path, release / path)
    for path in ("compiler.txt", "build-packages.txt", "config.log"):
        shutil.copyfile(OUT / "media" / path, release / path)
    files = []
    for path in sorted(release.iterdir()):
        files.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (release / "checksums.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    first = json.loads((OUT / "repro-first.json").read_text())
    second = json.loads((RUNTIME / "inventory.json").read_text())
    assert first["files"] == second["files"], "Frozen payload reproducibility changed"


if __name__ == "__main__":
    main()
