# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check shipped component licenses against security/license-policy.json (M30).

    uv run python scripts/security/check_licenses.py --live
    uv run python scripts/security/check_licenses.py --sbom sbom.cdx.json

``--live`` collects the Python runtime closure and the Windows Rust closure from
the lockfiles (JavaScript needs an inventory, so it is checked through the SBOM).
Exits non-zero for a denied, unknown or unapproved license.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import ROOT, python_components, rust_components  # noqa: E402

POLICY = ROOT / "security" / "license-policy.json"
_TOKEN = re.compile(r"\(|\)|\bAND\b|\bOR\b|[^\s()]+(?:\s+WITH\s+[^\s()]+)?")


def evaluate(expression: str, ok: Any) -> bool:
    """Evaluate an SPDX expression; ``ok(license_id)`` decides single terms.
    AND binds tighter than OR; ``A WITH B`` is one term."""
    tokens = _TOKEN.findall(" ".join(expression.split()))
    position = 0

    def term() -> bool:
        nonlocal position
        if position >= len(tokens):
            return False
        token = tokens[position]
        position += 1
        if token == "(":
            value = alternatives()
            position += 1  # ")"
            return value
        return bool(ok(token))

    def conjunction() -> bool:
        nonlocal position
        value = term()
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            value = term() and value
        return value

    def alternatives() -> bool:
        nonlocal position
        value = conjunction()
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            value = conjunction() or value
        return value

    return alternatives()


def judge(name: str, expression: str, policy: dict[str, Any]) -> str | None:
    """None when allowed, otherwise the reason it is not."""
    expression = " ".join(expression.split())
    if not expression or expression == "NOASSERTION":
        return "no license information"
    allowed = set(policy["allowed"])
    denied = set(policy["denied"])
    conditional = {
        (rule["license"], component)
        for rule in policy["conditional"]
        for component in rule["components"]
    }

    def ok(license_id: str) -> bool:
        if license_id in denied:
            return False
        return license_id in allowed or (license_id, name) in conditional

    if any(d in expression for d in denied) and not evaluate(expression, ok):
        return f"denied license in {expression}"
    return None if evaluate(expression, ok) else f"not allowed: {expression}"


def from_sbom(path: Path) -> list[tuple[str, str]]:
    bom = json.loads(path.read_text("utf-8"))
    out = []
    for component in bom["components"]:
        if component["type"] == "file":
            continue
        licenses = component.get("licenses") or []
        expression = " AND ".join(
            f"({entry['expression']})"
            if " OR " in entry.get("expression", "")
            else entry.get("expression", "")
            for entry in licenses
        )
        out.append((component["name"], expression or "NOASSERTION"))
    return out


def live() -> list[tuple[str, str]]:
    policy = json.loads(POLICY.read_text("utf-8"))
    known = {
        f"{o['ecosystem']}:{o['name']}": o["license"] for o in policy.get("license_overrides", [])
    }
    out = []
    for component in [*python_components(), *rust_components()]:
        expression = component.license
        if expression == "NOASSERTION":
            expression = known.get(f"{component.ecosystem}:{component.name}", expression)
        out.append((component.name, expression))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true")
    group.add_argument("--sbom", type=Path)
    args = parser.parse_args()
    policy = json.loads(POLICY.read_text("utf-8"))
    entries = live() if args.live else from_sbom(args.sbom)
    problems = [(name, reason) for name, expr in entries if (reason := judge(name, expr, policy))]
    for name, reason in problems:
        print(f"LICENSE {name}: {reason}")
    print(f"{len(entries)} components checked, {len(problems)} license problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
