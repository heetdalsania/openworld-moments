# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble auditable Actions assets, never publish a release or include synthetic media."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_paths import redact  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/packaging"
RUNTIME = ROOT / "apps/desktop/src-tauri/bundle-input/runtime"


def write_sbom(installer: Path, release: Path) -> None:
    """Generate the CycloneDX SBOM for this package (M30)."""
    subprocess.run(  # noqa: S603 - fixed script and arguments
        [
            sys.executable,
            str(ROOT / "scripts/security/sbom.py"),
            "--inventory",
            str(RUNTIME / "inventory.json"),
            "--installer",
            str(installer),
            "--output",
            str(release / "sbom.cdx.json"),
        ],
        check=True,
    )


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
    # M34: the freeze steps shared with macOS are part of the corresponding source.
    shutil.copyfile(ROOT / "scripts/packaging/runtime_bundle.py", release / "runtime_bundle.py")
    # Build notes name the CI workspace and temp folders; ship them redacted (M30).
    # FFmpeg's config.log is not shipped: autoconf dumps the whole CI environment into
    # it. The exact sources, build script, compiler, packages and configure line
    # (runtime inventory) are what corresponding source needs.
    for path in ("compiler.txt", "build-packages.txt"):
        text = (OUT / "media" / path).read_text("utf-8", errors="replace")
        (release / path).write_text(redact(text), encoding="utf-8")
    # M30: a CycloneDX SBOM of exactly this package, plus the disclosure policy and
    # verification instructions, all covered by checksums.txt below.
    write_sbom(release / "OpenWorld-Moments_0.1.0-alpha.29_Windows_x64-setup.exe", release)
    shutil.copyfile(ROOT / "SECURITY.md", release / "SECURITY.md")
    shutil.copyfile(ROOT / "docs/security/release-verification.md", release / "VERIFY.md")
    files = []
    for path in sorted(release.iterdir()):
        files.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (release / "checksums.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    first = json.loads((OUT / "repro-first.json").read_text())
    second = json.loads((RUNTIME / "inventory.json").read_text())
    assert first["files"] == second["files"], "Frozen payload reproducibility changed"


if __name__ == "__main__":
    main()
