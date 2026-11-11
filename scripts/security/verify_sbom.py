# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verify the SBOM against the package it describes (M30).

    uv run python scripts/security/verify_sbom.py --sbom sbom.cdx.json \
        --inventory <runtime/inventory.json> [--runtime-dir <runtime>] [--release-dir <release>]

1. The SBOM is valid CycloneDX 1.6 (strict schema).
2. Regenerating it from the same inputs gives the same content, so it reflects
   uv.lock, Cargo.lock, the runtime inventory and the model catalog exactly.
3. With ``--runtime-dir``: every packaged file on disk has exactly one file
   component with its SHA-256, and there are no extra or missing files.
4. With ``--release-dir``: checksums.txt verifies every artifact, the SBOM included.
5. Every shipped component passes the license policy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_licenses import POLICY, from_sbom, judge  # noqa: E402
from sbom import build, sha256  # noqa: E402


def schema_errors(text: str) -> list[str]:
    from cyclonedx.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    errors = JsonStrictValidator(SchemaVersion.V1_6).validate_str(text, all_errors=True)
    return [str(e)[:300] for e in errors] if errors else []


def comparable(bom: dict[str, Any]) -> dict[str, Any]:
    """The SBOM without the installer hash, which depends on --installer."""
    copy: dict[str, Any] = json.loads(json.dumps(bom))
    root = copy["metadata"]["component"]
    root.pop("hashes", None)
    root["properties"] = [p for p in root["properties"] if p["name"] != "owm:installer"]
    return copy


def verify(
    sbom_path: Path,
    inventory_path: Path,
    runtime: Path | None = None,
    release: Path | None = None,
) -> list[str]:
    problems: list[str] = []
    text = sbom_path.read_text("utf-8")
    problems += [f"schema: {e}" for e in schema_errors(text)]
    bom = json.loads(text)
    inventory = json.loads(inventory_path.read_text("utf-8"))
    if comparable(bom) != comparable(build(inventory, None)):
        problems.append("drift: the SBOM differs from one regenerated from its inputs")
    files = {
        c["name"].removeprefix("runtime/"): c["hashes"][0]["content"]
        for c in bom["components"]
        if c["type"] == "file"
    }
    if files != inventory["files"]:
        problems.append("files: SBOM file components differ from the runtime inventory")
    if runtime is not None:
        # The inventory cannot list its own hash; checksums.txt covers it as
        # runtime-inventory.json.
        on_disk = {
            p.relative_to(runtime).as_posix(): sha256(p)
            for p in sorted(runtime.rglob("*"))
            if p.is_file() and p.relative_to(runtime).as_posix() != "inventory.json"
        }
        missing = sorted(set(on_disk) - set(files))
        extra = sorted(set(files) - set(on_disk))
        changed = sorted(k for k in set(on_disk) & set(files) if on_disk[k] != files[k])
        for label, names in (("unlisted", missing), ("absent", extra), ("hash", changed)):
            if names:
                problems.append(f"package {label}: {len(names)} files, e.g. {names[:3]}")
    if release is not None:
        sums = {}
        for line in (release / "checksums.txt").read_text("utf-8").splitlines():
            digest, _, name = line.partition("  ")
            sums[name] = digest
        if sbom_path.name not in sums:
            problems.append("checksums: the SBOM is not listed in checksums.txt")
        for name, digest in sums.items():
            path = release / name
            if not path.is_file():
                problems.append(f"checksums: {name} is missing")
            elif sha256(path) != digest:
                problems.append(f"checksums: {name} does not match")
    policy = json.loads(POLICY.read_text("utf-8"))
    for name, expression in from_sbom(sbom_path):
        if reason := judge(name, expression, policy):
            problems.append(f"license: {name}: {reason}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--release-dir", type=Path)
    args = parser.parse_args()
    problems = verify(args.sbom, args.inventory, args.runtime_dir, args.release_dir)
    for problem in problems:
        print(f"FAIL {problem}")
    print("SBOM verified" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
