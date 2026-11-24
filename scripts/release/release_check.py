# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent checks of a Windows alpha release set before it is attached to a draft (M32).

Two read-only subcommands, both writing machine-readable JSON:

- ``verify-artifacts DIR --version V``: the downloaded CI release set is complete,
  every file matches ``checksums.txt`` and every file is listed, there is exactly one
  installer and it is the expected version (never the test-only upgrade build), and the
  runtime inventory, SBOM and native smoke reports all name the same version.
- ``ci-summary RUN.json``: summarizes ``gh run view --json ...`` output and fails unless
  the run finished and every job succeeded (named jobs may be allowed to skip).

Nothing here downloads, uploads, tags or publishes. The maintainer drives ``gh``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))

from release_version import (  # noqa: E402
    VERSION,
    installer_name,
    upgrade_test_version,
)

CHECKSUMS = "checksums.txt"
_LINE = re.compile(r"^([0-9a-f]{64})  ([^\\/\x00-\x1f]+)$")
# Every public release set carries these besides the installer (M29/M30 artifacts.py).
REQUIRED = (
    CHECKSUMS,
    "sbom.cdx.json",
    "runtime-inventory.json",
    "THIRD_PARTY_NOTICES.txt",
    "runtime-notices.zip",
    "SECURITY.md",
    "VERIFY.md",
    "sources.json",
    "build-media.sh",
    "reproducibility.json",
    "native-import-render.json",
    "native-repair.json",
    "native-upgrade.json",
    "native-uninstall.json",
)
CHUNK = 1 << 20


class Report:
    """Ordered named checks; the release passes only when every check passes."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, check_id: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"id": check_id, "ok": bool(ok), "detail": detail})
        return ok

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    """``<sha256>  <name>`` lines; plain names only, no duplicates, no blank entries."""
    entries: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        match = _LINE.fullmatch(line)
        if not match or match.group(2) in {".", ".."}:
            raise ValueError(f"{CHECKSUMS} line {number} is not '<sha256>  <file name>'")
        digest, name = match.groups()
        if name in entries:
            raise ValueError(f"{CHECKSUMS} lists {name} twice")
        entries[name] = digest
    if not entries:
        raise ValueError(f"{CHECKSUMS} is empty")
    return entries


def _json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8-sig"))


def _version_checks(report: Report, root: Path, version: str) -> None:
    def field(name: str, read: Any) -> None:
        path = root / name
        if not path.is_file():
            return  # already reported as missing
        try:
            found = read(_json(path))
        except (ValueError, KeyError, TypeError) as error:
            report.check(f"version:{name}", False, f"unreadable: {error}")
            return
        report.check(f"version:{name}", found == version, f"found {found!r}")

    field("runtime-inventory.json", lambda d: d["application"])
    field("sbom.cdx.json", lambda d: d["metadata"]["component"]["version"])
    field("native-import-render.json", lambda d: d["application"]["version"])
    field("native-repair.json", lambda d: d["application"]["version"])
    upgrade = root / "native-upgrade.json"
    if upgrade.is_file():
        try:
            found = _json(upgrade)["application"]["version"]
        except (ValueError, KeyError, TypeError) as error:
            report.check("version:native-upgrade.json", False, f"unreadable: {error}")
        else:
            expected = upgrade_test_version(version)
            report.check("version:native-upgrade.json", found == expected, f"found {found!r}")
    sbom = root / "sbom.cdx.json"
    if sbom.is_file():
        try:
            fmt = _json(sbom).get("bomFormat")
        except ValueError:
            fmt = None
        report.check("sbom:format", fmt == "CycloneDX", f"bomFormat {fmt!r}")
    repro = root / "reproducibility.json"
    if repro.is_file():
        try:
            same = _json(repro).get("frozen_payload_identical") is True
        except (ValueError, AttributeError):
            same = False
        report.check("reproducibility:frozen-payload", same)


def verify_artifacts(root: Path, version: str) -> dict[str, Any]:
    """Check one downloaded release folder. Never modifies it."""
    report = Report()
    if not VERSION.fullmatch(version):
        raise ValueError(f"Version must look like 0.1.0-alpha.N, got {version!r}")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Release folder must be a real directory")
    entries = sorted(root.iterdir(), key=lambda p: p.name)
    odd = [p.name for p in entries if p.is_symlink() or not p.is_file()]
    report.check("layout:plain-files", not odd, ", ".join(odd))
    files = {p.name: p for p in entries if p.is_file() and not p.is_symlink()}

    installer = installer_name(version)
    installers = sorted(n for n in files if n.lower().endswith(".exe"))
    report.check("installer:exactly-one", installers == [installer], ", ".join(installers))
    for name in (installer, *REQUIRED):
        report.check(f"present:{name}", name in files)

    listed: dict[str, str] = {}
    if CHECKSUMS in files:
        try:
            listed = parse_checksums(files[CHECKSUMS].read_text("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            report.check("checksums:format", False, str(error))
        else:
            report.check("checksums:format", True)
    if listed:
        report.check("checksums:not-self-listed", CHECKSUMS not in listed)
        unlisted = sorted(set(files) - set(listed) - {CHECKSUMS})
        report.check("checksums:every-file-listed", not unlisted, ", ".join(unlisted))
        missing = sorted(set(listed) - set(files))
        report.check("checksums:every-listed-file-present", not missing, ", ".join(missing))
        bad = sorted(n for n, d in listed.items() if n in files and sha256(files[n]) != d)
        report.check("checksums:match", not bad, ", ".join(bad))
    _version_checks(report, root, version)
    return {
        "format_version": 1,
        "version": version,
        "ok": report.ok,
        "checks": report.checks,
        "files": [
            {"name": name, "sha256": sha256(path), "bytes": path.stat().st_size}
            for name, path in sorted(files.items())
        ],
    }


def hash_table(result: dict[str, Any]) -> str:
    """Markdown table of the verified files, for the qualification report."""
    rows = ["| File | Bytes | SHA-256 |", "|---|---:|---|"]
    rows += [f"| `{f['name']}` | {f['bytes']:,} | `{f['sha256']}` |" for f in result["files"]]
    return "\n".join(rows) + "\n"


def ci_summary(run: dict[str, Any], allow_skipped: Sequence[str] = ()) -> dict[str, Any]:
    """Summarize ``gh run view --json databaseId,headSha,event,status,conclusion,url,jobs``."""
    jobs = run.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("Run JSON has no jobs; pass --json ...,jobs to gh run view")
    allowed = set(allow_skipped)
    summary = []
    for job in jobs:
        name, conclusion = str(job.get("name", "")), job.get("conclusion")
        ok = conclusion == "success" or (conclusion == "skipped" and name in allowed)
        summary.append({"name": name, "conclusion": conclusion, "ok": ok})
    finished = run.get("status") == "completed"
    return {
        "format_version": 1,
        "run_id": run.get("databaseId"),
        "url": run.get("url"),
        "event": run.get("event"),
        "head_sha": run.get("headSha"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "ok": finished and all(j["ok"] for j in summary),
        "jobs": sorted(summary, key=lambda j: j["name"]),
    }


def _write(result: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-artifacts", help="check a downloaded release folder")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--version", required=True)
    verify.add_argument("--report", type=Path, help="write JSON here instead of stdout")
    verify.add_argument("--markdown", type=Path, help="also write a Markdown hash table")
    summary = commands.add_parser("ci-summary", help="summarize gh run view --json output")
    summary.add_argument("run_json", type=Path)
    summary.add_argument("--allow-skipped", action="append", default=[], metavar="JOB")
    summary.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.command == "verify-artifacts":
        directory = args.directory.resolve()
        for out in (args.report, args.markdown):
            if out is not None and out.resolve().parent == directory:
                parser.error("write reports outside the release folder")
        result = verify_artifacts(directory, args.version)
        _write(result, args.report)
        if args.markdown is not None:
            args.markdown.write_text(hash_table(result), encoding="utf-8")
    else:
        result = ci_summary(_json(args.run_json), args.allow_skipped)
        _write(result, args.report)
    for check in result.get("checks", result.get("jobs", [])):
        if not check["ok"]:
            label = check.get("id", check.get("name"))
            detail = check.get("detail", check.get("conclusion", ""))
            print(f"FAILED {label}: {detail}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
