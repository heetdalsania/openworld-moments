# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build, verify and package an unsigned macOS development shell (M33).

    python scripts/macos/build-shell.py --arch arm64     # or x86_64
    python scripts/macos/build-shell.py --arch x86_64 --skip-build --no-run

Steps (every external program is started by argument array, never through a shell):

1. `tauri build --target <triple> --bundles app` with `MACOSX_DEPLOYMENT_TARGET` set to
   the supported floor, so the binary and `Info.plist` agree.
2. Check every Mach-O file in the bundle is a thin binary of the requested
   architecture that runs on the floor, and that the host executable targets it exactly.
3. Check `Info.plist` declares the floor and the expected executable.
4. Run the executable with `--version-report` (unless `--no-run`, used when building
   for the other architecture) and check it reports the expected build natively.
5. Zip the bundle with `ditto`, keeping macOS metadata, and write `build-info.json`
   and `SHA256SUMS.txt` next to it in `output/packaging/macos/`.

The result is a development artifact: unsigned, not notarized, without the worker or
media tools (M34). Opening it needs right-click → Open on the test Mac; see
`docs/platforms/macos-development-shell.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from macho import check_native, is_macho, read

ROOT = Path(__file__).resolve().parents[2]
FLOOR = "14.0"
TARGETS = {"arm64": "aarch64-apple-darwin", "x86_64": "x86_64-apple-darwin"}
REPORT_ARCH = {"arm64": "aarch64", "x86_64": "x86_64"}
APP = "OpenWorld Moments.app"
OUTPUT = ROOT / "output" / "packaging" / "macos"


def artifact_name(version: str, arch: str, commit: str) -> str:
    """`OpenWorld-Moments_<version>+<commit>_macOS_<arch>_unsigned-dev.zip`."""
    if arch not in TARGETS:
        raise ValueError(f"unknown architecture {arch!r}")
    safe = "".join(c for c in version if c.isalnum() or c in ".-")
    short = "".join(c for c in commit[:7] if c in "0123456789abcdef") or "unknown"
    return f"OpenWorld-Moments_{safe}+{short}_macOS_{arch}_unsigned-dev.zip"


def build(arch: str) -> None:
    env = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": FLOOR}
    command = [
        "pnpm",
        "--filter",
        "@openworld-moments/desktop",
        "run",
        "tauri",
        "build",
        "--target",
        TARGETS[arch],
        "--bundles",
        "app",
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)  # noqa: S603


def bundle_path(arch: str) -> Path:
    return ROOT / "target" / TARGETS[arch] / "release" / "bundle" / "macos" / APP


def verify_bundle(app: Path, arch: str, floor: str = FLOOR) -> list[str]:
    """Every problem with the bundle; empty when it is a native `arch` shell."""
    problems: list[str] = []
    info_path = app / "Contents" / "Info.plist"
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        return [f"Info.plist: {error}"]
    if info.get("LSMinimumSystemVersion") != floor:
        problems.append(
            f"Info.plist: LSMinimumSystemVersion is {info.get('LSMinimumSystemVersion')!r}, "
            f"expected {floor!r}"
        )
    executable = app / "Contents" / "MacOS" / str(info.get("CFBundleExecutable", ""))
    if not info.get("CFBundleExecutable") or not executable.is_file():
        return [*problems, "Info.plist: CFBundleExecutable is missing from Contents/MacOS"]
    binaries = sorted(
        p for p in app.rglob("*") if p.is_file() and not p.is_symlink() and is_macho(p)
    )
    if executable not in binaries:
        problems.append(f"{executable.name}: not a Mach-O executable")
    for binary in binaries:
        problems.extend(check_native(binary, arch, floor))
    if executable in binaries and not problems:
        (main,) = read(executable)
        if main.minimum != floor:
            problems.append(
                f"{executable.name}: targets macOS {main.minimum}; "
                f"MACOSX_DEPLOYMENT_TARGET={floor} was not applied"
            )
    return problems


def check_report(report: dict[str, object], arch: str) -> list[str]:
    """The `--version-report` of a native shell on a supported Mac."""

    def part(name: str) -> dict[str, object]:
        value = report.get(name)
        return value if isinstance(value, dict) else {}

    problems = []
    os_info, architecture, build_info = part("os"), part("architecture"), part("build")
    if os_info.get("family") != "macos" or os_info.get("minimum") != FLOOR:
        problems.append(f"os: {os_info}")
    if architecture.get("binary") != REPORT_ARCH[arch]:
        problems.append(f"architecture: {architecture}")
    if architecture.get("translated") is not False:
        problems.append(f"architecture: not running natively ({architecture})")
    if build_info.get("target") != TARGETS[arch] or build_info.get("profile") != "release":
        problems.append(f"build: {build_info}")
    return problems


def version_report(app: Path) -> dict[str, object]:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    executable = app / "Contents" / "MacOS" / str(info["CFBundleExecutable"])
    result = subprocess.run(  # noqa: S603
        [str(executable), "--version-report"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env={"HOME": os.environ.get("HOME", "/"), "LANG": "C"},  # no shell PATH
    )
    report: dict[str, object] = json.loads(result.stdout)
    return report


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def package(app: Path, arch: str, report: dict[str, object] | None) -> Path:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    version = str(info.get("CFBundleShortVersionString", "0.0.0"))
    commit = git_commit()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / artifact_name(version, arch, commit)
    archive.unlink(missing_ok=True)
    subprocess.run(  # noqa: S603
        ["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    meta = {
        "artifact": archive.name,
        "sha256": digest,
        "version": version,
        "commit": commit,
        "architecture": arch,
        "target": TARGETS[arch],
        "minimum_macos": FLOOR,
        "signed": False,
        "notarized": False,
        "bundled_worker": False,
        "version_report": report,
        "note": "Development artifact. Unsigned, not notarized, no worker or media tools.",
    }
    (OUTPUT / f"build-info-{arch}.json").write_text(json.dumps(meta, indent=2) + "\n", "utf-8")
    with (OUTPUT / "SHA256SUMS.txt").open("a", encoding="ascii") as sums:
        sums.write(f"{digest}  {archive.name}\n")
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--arch", choices=sorted(TARGETS), required=True)
    parser.add_argument("--skip-build", action="store_true", help="verify an existing bundle")
    parser.add_argument("--no-run", action="store_true", help="do not start the executable")
    parser.add_argument("--no-package", action="store_true", help="verify only")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("macOS shells are built on macOS", file=sys.stderr)
        return 2
    if not args.skip_build:
        build(args.arch)
    app = bundle_path(args.arch)
    problems = verify_bundle(app, args.arch)
    report = None
    if not problems and not args.no_run:
        report = version_report(app)
        problems = check_report(report, args.arch)
        print(json.dumps(report, indent=2))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"verified native {args.arch} shell for macOS {FLOOR}+")
    if not args.no_package:
        print(f"packaged {package(app, args.arch, report).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
