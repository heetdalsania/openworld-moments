# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collect the components that ship in the Windows package (M30).

Shared by the SBOM generator, its verifier and the license check, so all three
agree on what "shipped" means:

- Python: the worker's locked runtime closure from uv.lock (no dev or packaging
  groups), with markers evaluated for 64-bit CPython on Windows.
- Rust: the desktop executable's normal-dependency closure for
  x86_64-pc-windows-msvc (build and dev dependencies do not ship).
- JavaScript: the production packages recorded in the runtime inventory when the
  worker was frozen (`pnpm licenses list --prod`).
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_TARGET = "x86_64-pc-windows-msvc"
DESKTOP_CRATE = "openworld-moments-desktop"
#: Marker environment of the packaged runtime (64-bit CPython 3.12 on Windows).
MARKERS = {
    "sys_platform": "win32",
    "platform_system": "Windows",
    "os_name": "nt",
    "platform_python_implementation": "CPython",
    "implementation_name": "cpython",
    "python_version": "3.12",
    "platform_machine": "AMD64",
}
WORKSPACE_PYTHON = {
    "openworld-moments-worker": "AGPL-3.0-or-later",
    "openworld-moments-contracts": "Apache-2.0",
}


@dataclass(frozen=True, order=True)
class Component:
    ecosystem: str  # pypi | cargo | npm | generic
    name: str
    version: str
    license: str = "NOASSERTION"
    purl: str = ""
    extra: tuple[tuple[str, str], ...] = field(default=(), compare=False)


def _run(args: list[str]) -> str:
    executable = shutil.which(args[0])
    if executable is None:
        raise RuntimeError(f"{args[0]} is required")
    return subprocess.check_output(  # noqa: S603 - fixed tool and arguments
        [executable, *args[1:]], cwd=ROOT, text=True, encoding="utf-8"
    )


# -- Python -----------------------------------------------------------------------------

_CLAUSE = re.compile(r"\s*(\w+)\s*(==|!=|<=|>=|<|>)\s*'([^']*)'\s*")


def marker_applies(marker: str) -> bool:
    """Evaluate the simple PEP 508 markers uv emits (``name op 'value'`` joined by
    ``and``/``or``) against :data:`MARKERS`. Anything else counts as applying."""
    marker = marker.strip()
    if not marker:
        return True
    for alternative in re.split(r"\s+or\s+", marker):
        results = []
        for clause in re.split(r"\s+and\s+", alternative.strip("() ")):
            match = _CLAUSE.fullmatch(clause.strip("() "))
            if match is None:
                results.append(True)
                continue
            name, op, value = match.groups()
            actual = MARKERS.get(name, "")
            results.append(
                {
                    "==": actual == value,
                    "!=": actual != value,
                    "<": actual < value,
                    ">": actual > value,
                    "<=": actual <= value,
                    ">=": actual >= value,
                }[op]
            )
        if all(results):
            return True
    return False


def python_license(name: str) -> str:
    try:
        meta = importlib.metadata.metadata(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOASSERTION"
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    mapped = sorted({_CLASSIFIERS[c] for c in classifiers if c in _CLASSIFIERS})
    if mapped:
        return " OR ".join(mapped)
    raw = (meta.get("License") or "").strip()
    return _LICENSE_TEXT.get(raw, raw) if raw and len(raw) < 80 else "NOASSERTION"


_CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
_LICENSE_TEXT = {"MIT License": "MIT", "BSD": "BSD-3-Clause", "Apache 2.0": "Apache-2.0"}


def python_components() -> list[Component]:
    exported = _run(
        [
            "uv",
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
    components = []
    for line in exported.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement, _, marker = line.partition(";")
        name, _, version = requirement.strip().partition("==")
        if not version or not marker_applies(marker):
            continue
        name = name.strip().lower()
        components.append(
            Component(
                "pypi",
                name,
                version.strip(),
                python_license(name),
                f"pkg:pypi/{name}@{version.strip()}",
            )
        )
    for name, license_id in WORKSPACE_PYTHON.items():
        components.append(
            Component(
                "pypi",
                name,
                "0.0.0",
                license_id,
                f"pkg:pypi/{name}@0.0.0",
                (("source", "workspace"),),
            )
        )
    return sorted(components)


# -- Rust -------------------------------------------------------------------------------


def rust_components() -> list[Component]:
    metadata: dict[str, Any] = json.loads(
        _run(
            [
                "cargo",
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                WINDOWS_TARGET,
            ]
        )
    )
    packages = {p["id"]: p for p in metadata["packages"]}
    nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
    root = next(p["id"] for p in metadata["packages"] if p["name"] == DESKTOP_CRATE)
    seen: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for dep in nodes[current]["deps"]:
            if any(kind["kind"] is None for kind in dep["dep_kinds"]):
                stack.append(dep["pkg"])
    components = []
    for package_id in seen:
        package = packages[package_id]
        source = package.get("source") or ""
        extra = () if source.startswith("registry+") else (("source", "workspace"),)
        components.append(
            Component(
                "cargo",
                package["name"],
                package["version"],
                (package.get("license") or "NOASSERTION").replace("/", " OR "),
                f"pkg:cargo/{package['name']}@{package['version']}",
                extra,
            )
        )
    return sorted(components)


# -- JavaScript -------------------------------------------------------------------------


def javascript_components(inventory: dict[str, Any]) -> list[Component]:
    components = []
    for package in inventory.get("javascript_packages", []):
        for version in package["versions"]:
            name = package["name"]
            purl_name = name.replace("@", "%40", 1) if name.startswith("@") else name
            components.append(
                Component(
                    "npm",
                    name,
                    version,
                    package.get("license") or "NOASSERTION",
                    f"pkg:npm/{purl_name}@{version}",
                )
            )
    return sorted(components)


def tally(components: list[Component]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for component in components:
        counts[component.license] = counts.get(component.license, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
