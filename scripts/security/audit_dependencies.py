# SPDX-License-Identifier: AGPL-3.0-or-later
"""Known-vulnerability gate for shipped dependencies (M30). Queries online databases.

    uv run python scripts/security/audit_dependencies.py [--report out.json]

- Python: the worker's locked runtime closure (uv.lock, no dev/packaging groups),
  audited with pip-audit against PyPI/OSV advisories. Any known vulnerability fails.
- Rust: Cargo.lock with cargo-audit (RustSec). Any vulnerability fails; unsound and
  unmaintained warnings are reported but do not fail.
- JavaScript: production dependencies with ``pnpm audit --prod``. High or critical
  advisories fail.

A finding passes only if security/vulnerability-exceptions.json lists its ID with
a reason and an unexpired review date.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS = ROOT / "security" / "vulnerability-exceptions.json"
PIP_AUDIT = "pip-audit==2.10.1"


def tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"{name} is required")
    return path


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed tools and arguments
        args, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False
    )


def active_exceptions(today: dt.date) -> tuple[set[str], list[str]]:
    data = json.loads(EXCEPTIONS.read_text("utf-8"))
    ids, expired = set(), []
    for entry in data["exceptions"]:
        if dt.date.fromisoformat(entry["review_by"]) < today:
            expired.append(f"{entry['id']} (review was due {entry['review_by']})")
        else:
            ids.add(entry["id"])
    return ids, expired


def python_findings() -> list[dict[str, str]]:
    exported = run(
        [
            tool("uv"),
            "export",
            "--frozen",
            "--no-dev",
            "--no-hashes",
            "--no-emit-workspace",
            "--no-header",
            "--package",
            "openworld-moments-worker",
        ]
    )
    if exported.returncode:
        raise RuntimeError(exported.stderr)
    with tempfile.TemporaryDirectory() as folder:
        requirements = Path(folder) / "runtime.txt"
        requirements.write_text(exported.stdout, encoding="utf-8")
        audited = run(
            [
                tool("uvx"),
                "--from",
                PIP_AUDIT,
                "pip-audit",
                "--disable-pip",
                "--no-deps",
                "-r",
                str(requirements),
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ]
        )
    if audited.returncode not in (0, 1) or not audited.stdout.strip():
        raise RuntimeError(audited.stderr)
    report = json.loads(audited.stdout)
    return [
        {
            "ecosystem": "pypi",
            "package": f"{d['name']} {d['version']}",
            "id": v["id"],
            "aliases": " ".join(v.get("aliases", [])),
            "severity": "unknown",
        }
        for d in report["dependencies"]
        for v in d.get("vulns", [])
    ]


def rust_findings() -> tuple[list[dict[str, str]], list[str]]:
    audited = run([tool("cargo"), "audit", "--json"])
    if not audited.stdout.strip():
        raise RuntimeError(audited.stderr)
    report = json.loads(audited.stdout)
    findings = [
        {
            "ecosystem": "cargo",
            "package": f"{v['package']['name']} {v['package']['version']}",
            "id": v["advisory"]["id"],
            "aliases": " ".join(v["advisory"].get("aliases", [])),
            "severity": str((v["advisory"].get("cvss") or "unknown")),
        }
        for v in report["vulnerabilities"]["list"]
    ]
    warnings = [
        f"{kind}: {w['package']['name']} {w['package']['version']} "
        f"{(w.get('advisory') or {}).get('id', '')}"
        for kind, items in report.get("warnings", {}).items()
        for w in items
    ]
    return findings, warnings


def javascript_findings() -> list[dict[str, str]]:
    audited = run([tool("pnpm"), "audit", "--prod", "--json"])
    if not audited.stdout.strip():
        raise RuntimeError(audited.stderr)
    report = json.loads(audited.stdout)
    return [
        {
            "ecosystem": "npm",
            "package": f"{a['module_name']} {a.get('vulnerable_versions', '')}",
            "id": a.get("github_advisory_id") or str(a.get("id")),
            "aliases": " ".join(a.get("cves", [])),
            "severity": a["severity"],
        }
        for a in (report.get("advisories") or {}).values()
        if a["severity"] in ("high", "critical")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    allowed, expired = active_exceptions(dt.date.today())
    rust, warnings = rust_findings()
    findings = [*python_findings(), *rust, *javascript_findings()]
    blocking = [
        f for f in findings if f["id"] not in allowed and not (set(f["aliases"].split()) & allowed)
    ]
    report: dict[str, Any] = {
        "findings": findings,
        "blocking": blocking,
        "warnings": warnings,
        "expired": expired,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for f in blocking:
        print(f"VULNERABLE {f['ecosystem']} {f['package']}: {f['id']} ({f['severity']})")
    for warning in warnings:
        print(f"WARNING {warning}")
    for item in expired:
        print(f"EXPIRED EXCEPTION {item}")
    print(
        f"{len(findings)} known vulnerabilities, {len(findings) - len(blocking)} with documented "
        f"exceptions, {len(blocking)} blocking; {len(warnings)} advisory warnings"
    )
    return 1 if blocking or expired else 0


if __name__ == "__main__":
    sys.exit(main())
