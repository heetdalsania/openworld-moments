# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scan release artifacts for secrets and absolute paths (M30).

Every file under the given folders is read as bytes (binaries included). A finding
fails the scan unless ``security/artifact-scan-exceptions.json`` lists it with a
reason. Exceptions name a path glob and a pattern kind; each must still match
something, so a stale exception fails too.

    python scripts/security/scan_artifacts.py <folder> [<folder> ...] [--report out.json]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS = ROOT / "security" / "artifact-scan-exceptions.json"
MAX_BYTES = 256 * 1024 * 1024

PATTERNS: dict[str, re.Pattern[bytes]] = {
    # Personal or CI home folders: C:\Users\<name>, /Users/<name>, /home/<name>.
    "home-path": re.compile(
        rb"[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9._~ -]+[\\/]|/(?:Users|home)/[a-z0-9._-]+/"
    ),
    # GitHub Actions workspaces and temp folders of this repository's builds.
    "ci-workspace": re.compile(rb"[A-Za-z]:[\\/]a[\\/]openworld-moments|/d/a/openworld-moments"),
    "private-key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github-token": re.compile(
        rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|github_pat_[A-Za-z0-9_]{60,}"
    ),
    "aws-key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "slack-token": re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
}


def scan(folders: list[Path]) -> list[dict[str, str]]:
    findings = []
    for folder in folders:
        paths = [folder] if folder.is_file() else sorted(folder.rglob("*"))
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            if path.stat().st_size > MAX_BYTES:
                findings.append({"file": rel(path, folders), "kind": "too-large", "sample": ""})
                continue
            data = path.read_bytes()
            for kind, pattern in PATTERNS.items():
                match = pattern.search(data)
                if match:
                    sample = data[match.start() : match.end() + 40].decode("latin-1")
                    findings.append(
                        {"file": rel(path, folders), "kind": kind, "sample": printable(sample)}
                    )
    return findings


def rel(path: Path, folders: list[Path]) -> str:
    for folder in folders:
        if folder.is_file() and path == folder:
            return folder.name
        if path.is_relative_to(folder):
            return f"{folder.name}/{path.relative_to(folder).as_posix()}"
    return path.name


def printable(text: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else "." for c in text)[:120]


def judge(
    findings: list[dict[str, str]], exceptions: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(unexplained findings, stale exceptions)."""
    used: set[int] = set()
    unexplained = []
    for finding in findings:
        for i, rule in enumerate(exceptions):
            if finding["kind"] == rule["kind"] and fnmatch.fnmatch(finding["file"], rule["path"]):
                used.add(i)
                break
        else:
            unexplained.append(finding)
    stale = [rule for i, rule in enumerate(exceptions) if i not in used]
    return unexplained, stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS)
    args = parser.parse_args()
    exceptions = json.loads(args.exceptions.read_text("utf-8"))["exceptions"]
    findings = scan([f.resolve() for f in args.folders])
    unexplained, stale = judge(findings, exceptions)
    report = {"findings": findings, "unexplained": unexplained, "stale_exceptions": stale}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for finding in unexplained:
        print(f"FINDING {finding['kind']}: {finding['file']}: {finding['sample']}")
    for rule in stale:
        print(f"STALE EXCEPTION {rule['kind']}: {rule['path']} ({rule['reason']})")
    print(
        f"{len(findings)} findings, {len(findings) - len(unexplained)} explained by "
        f"documented exceptions, {len(unexplained)} unexplained, {len(stale)} stale exceptions"
    )
    return 1 if unexplained or stale else 0


if __name__ == "__main__":
    sys.exit(main())
