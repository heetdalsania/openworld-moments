# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate a CycloneDX 1.6 SBOM for a package (M30 Windows; M34 macOS per architecture).

Inputs are the ones that produce the package: the runtime inventory written when
the worker was frozen (every packaged file and its SHA-256, the bundled tools,
the JavaScript production packages and pinned sources), uv.lock, Cargo.lock and
the signed model catalog. Output is deterministic for the same inputs.

    uv run python scripts/security/sbom.py --inventory <runtime/inventory.json> \
        [--installer <setup.exe>] --output sbom.cdx.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import (  # noqa: E402
    ROOT,
    Component,
    javascript_components,
    profile,
    python_components,
    rust_components,
)

CATALOG = ROOT / "services/media-worker/openworld_moments/transcripts/catalog/models.json"
POLICY = ROOT / "security" / "license-policy.json"
#: Libraries the python-build-standalone runtime bundles, with a file that proves
#: each one is in the package (only those present are listed).
CPYTHON_LIBRARIES = {
    "openssl": ("Apache-2.0", "_internal/libcrypto-3-x64.dll"),
    "sqlite": ("blessing", "_internal/sqlite3.dll"),
    "libffi": ("MIT", "_internal/libffi-8.dll"),
    "bzip2": ("bzip2-1.0.6", "_internal/_bz2.pyd"),
    "xz-liblzma": ("0BSD", "_internal/_lzma.pyd"),
    "expat": ("MIT", "_internal/pyexpat.pyd"),
    "mpdecimal": ("BSD-2-Clause", "_internal/_decimal.pyd"),
    "zlib": ("Zlib", "_internal/python312.dll"),
}
#: M34: on macOS python-build-standalone links these into libpython; libffi, zlib,
#: libedit and ncurses come from macOS itself (the Mach-O audit lists them).
MACOS_CPYTHON_LIBRARIES = {
    name: (CPYTHON_LIBRARIES[name][0], "_internal/libpython3.12.dylib")
    for name in ("openssl", "sqlite", "bzip2", "xz-liblzma", "expat", "mpdecimal")
}


def platform_files(inventory: dict[str, Any]) -> tuple[str, dict[str, tuple[str, str]], str]:
    """(executable suffix, CPython libraries, webview note) for the package."""
    if inventory.get("platform", "windows") == "macos":
        return "", MACOS_CPYTHON_LIBRARIES, "Apple-managed macOS WebKit (WKWebView); not bundled"
    return ".exe", CPYTHON_LIBRARIES, "Microsoft-managed Windows component; not bundled"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def license_field(expression: str) -> list[dict[str, Any]]:
    expression = " ".join(expression.split())
    if expression in ("", "NOASSERTION"):
        return []
    return [{"expression": expression}]


def overrides() -> dict[str, str]:
    """Licenses for packages the generating host may not have installed."""
    policy = json.loads(POLICY.read_text("utf-8"))
    return {
        f"{o['ecosystem']}:{o['name']}": o["license"] for o in policy.get("license_overrides", [])
    }


def library(component: Component, known: dict[str, str]) -> dict[str, Any]:
    license_id = component.license
    if license_id == "NOASSERTION":
        license_id = known.get(f"{component.ecosystem}:{component.name}", license_id)
    entry: dict[str, Any] = {
        "type": "library",
        "bom-ref": component.purl,
        "name": component.name,
        "version": component.version,
        "purl": component.purl,
    }
    if licenses := license_field(license_id):
        entry["licenses"] = licenses
    properties = [{"name": "owm:ecosystem", "value": component.ecosystem}]
    properties += [{"name": f"owm:{k}", "value": v} for k, v in component.extra]
    entry["properties"] = properties
    return entry


def native_components(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    files: dict[str, str] = inventory["files"]
    exe, cpython_libraries, _ = platform_files(inventory)
    tools = {tool["name"]: tool for tool in inventory["tools"]}
    sources = inventory["sources"]
    out: list[dict[str, Any]] = [
        {
            "type": "application",
            "bom-ref": f"pkg:generic/cpython@{inventory['python']}",
            "name": "cpython",
            "version": inventory["python"],
            "purl": f"pkg:generic/cpython@{inventory['python']}",
            "licenses": [{"expression": "PSF-2.0"}],
            "properties": [
                {
                    "name": "owm:distribution",
                    "value": f"python-build-standalone {inventory['python_build']}",
                },
                {
                    "name": "owm:notices-commit",
                    "value": inventory["python_notices"]["source_commit"],
                },
            ],
        },
        {
            "type": "application",
            "bom-ref": f"pkg:pypi/pyinstaller-bootloader@{inventory['pyinstaller']}",
            "name": "pyinstaller-bootloader",
            "version": inventory["pyinstaller"],
            "purl": f"pkg:pypi/pyinstaller@{inventory['pyinstaller']}",
            "licenses": [{"expression": "GPL-2.0-or-later WITH Bootloader-exception"}],
            "hashes": [{"alg": "SHA-256", "content": files[f"owm-worker{exe}"]}],
            "properties": [{"name": "owm:file", "value": f"runtime/owm-worker{exe}"}],
        },
    ]
    for name, (license_id, proof) in sorted(cpython_libraries.items()):
        if proof not in files:
            continue
        out.append(
            {
                "type": "library",
                "bom-ref": f"pkg:generic/{name}?bundled-with=cpython",
                "name": name,
                "licenses": [{"expression": license_id}],
                "hashes": [{"alg": "SHA-256", "content": files[proof]}],
                "properties": [
                    {"name": "owm:bundled-with", "value": "cpython"},
                    {"name": "owm:file", "value": f"runtime/{proof}"},
                ],
            }
        )
    if "openssl" in sources:  # M34 Intel: linked statically into cryptography's extension
        source = sources["openssl"]
        out.append(
            {
                "type": "library",
                "bom-ref": f"pkg:generic/openssl@{source['version']}?linked-into=cryptography",
                "name": "openssl",
                "version": source["version"],
                "purl": f"pkg:generic/openssl@{source['version']}",
                "licenses": [{"expression": source["license"]}],
                "externalReferences": [
                    {
                        "type": "source-distribution",
                        "url": source["url"],
                        "hashes": [{"alg": "SHA-256", "content": source["sha256"]}],
                    }
                ],
                "properties": [{"name": "owm:linked-into", "value": "cryptography"}],
            }
        )
    for name in ("ffmpeg", "x264"):
        source = sources[name]
        component: dict[str, Any] = {
            "type": "application" if name == "ffmpeg" else "library",
            "bom-ref": f"pkg:generic/{name}@{source['version']}",
            "name": name,
            "version": source["version"],
            "purl": f"pkg:generic/{name}@{source['version']}",
            "licenses": [{"expression": source["license"]}],
            "externalReferences": [
                {
                    "type": "source-distribution",
                    "url": source["url"],
                    "hashes": [{"alg": "SHA-256", "content": source["sha256"]}],
                }
            ],
            "properties": [{"name": "owm:license-decision", "value": "ADR-0007"}],
        }
        if name == "ffmpeg":
            component["hashes"] = [
                {"alg": "SHA-256", "content": tools[tool]["sha256"]}
                for tool in ("ffmpeg", "ffprobe")
            ]
            component["properties"].append(
                {"name": "owm:file", "value": f"runtime/tools/ffmpeg{exe}"}
            )
            component["properties"].append(
                {"name": "owm:file", "value": f"runtime/tools/ffprobe{exe}"}
            )
        out.append(component)
    return out


def model_components() -> list[dict[str, Any]]:
    catalog = json.loads(CATALOG.read_text("utf-8"))
    return [
        {
            "type": "machine-learning-model",
            "bom-ref": f"model:{model['name']}@{model['revision']}",
            "name": model["name"],
            "version": model["revision"],
            "scope": "excluded",
            "licenses": [{"expression": model["license"]}],
            "hashes": [{"alg": "SHA-256", "content": model["sha256"]}],
            "externalReferences": [{"type": "distribution", "url": model["url"]}],
            "properties": [
                {"name": "owm:bundled", "value": "false"},
                {
                    "name": "owm:install",
                    "value": "explicit user download, signature-checked catalog",
                },
                {"name": "owm:size-bytes", "value": str(model["size_bytes"])},
            ],
        }
        for model in catalog["models"]
    ]


def file_components(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "file",
            "bom-ref": f"file:runtime/{path}",
            "name": f"runtime/{path}",
            "hashes": [{"alg": "SHA-256", "content": digest}],
        }
        for path, digest in sorted(inventory["files"].items())
    ]


def commit_time(commit: str) -> str | None:
    try:
        return (
            subprocess.check_output(  # noqa: S603, S607 - fixed git query
                ["git", "show", "-s", "--format=%cI", commit],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            or None
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def platform_root_properties(inventory: dict[str, Any]) -> list[dict[str, str]]:
    note = platform_files(inventory)[2]
    if inventory.get("platform", "windows") == "macos":
        return [
            {"name": "owm:platform", "value": "macos"},
            {"name": "owm:minimum-macos", "value": inventory.get("minimum_macos", "")},
            {"name": "owm:webview", "value": note},
        ]
    return [{"name": "owm:webview2", "value": note}]


def build(inventory: dict[str, Any], installer: Path | None) -> dict[str, Any]:
    known = overrides()
    target, markers = profile(inventory)
    libraries = [
        library(c, known)
        for c in [
            *python_components(markers),
            *rust_components(target),
            *javascript_components(inventory),
        ]
    ]
    components = sorted(
        [
            *libraries,
            *native_components(inventory),
            *model_components(),
            *file_components(inventory),
        ],
        key=lambda c: (c["type"], c["name"], c.get("version", ""), c["bom-ref"]),
    )
    version = inventory["application"]
    root: dict[str, Any] = {
        "type": "application",
        "bom-ref": f"pkg:generic/openworld-moments@{version}",
        "name": "OpenWorld Moments",
        "version": version,
        "licenses": [{"expression": "AGPL-3.0-or-later"}],
        "properties": [
            {"name": "owm:commit", "value": inventory["commit"]},
            {"name": "owm:architecture", "value": inventory["architecture"]},
            *platform_root_properties(inventory),
        ],
    }
    if installer is not None:
        root["hashes"] = [{"alg": "SHA-256", "content": sha256(installer)}]
        root["properties"].append({"name": "owm:installer", "value": installer.name})
    metadata: dict[str, Any] = {
        "tools": {
            "components": [
                {"type": "application", "name": "openworld-moments-sbom", "version": "1"}
            ]
        },
        "component": root,
        "lifecycles": [{"phase": "build"}],
    }
    if timestamp := commit_time(inventory["commit"]):
        metadata["timestamp"] = timestamp
    shipped = [
        c["bom-ref"] for c in components if c.get("scope") != "excluded" and c["type"] != "file"
    ]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:"
        + str(uuid.uuid5(uuid.NAMESPACE_URL, f"openworld-moments:{inventory['commit']}:{version}")),
        "version": 1,
        "metadata": metadata,
        "components": components,
        "dependencies": [{"ref": root["bom-ref"], "dependsOn": sorted(shipped)}],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text("utf-8"))
    bom = build(inventory, args.installer)
    args.output.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    kinds: dict[str, int] = {}
    for component in bom["components"]:
        kinds[component["type"]] = kinds.get(component["type"], 0) + 1
    print(f"Wrote {args.output.name}: {kinds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
