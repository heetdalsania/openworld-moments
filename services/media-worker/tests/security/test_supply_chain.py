# SPDX-License-Identifier: AGPL-3.0-or-later
"""Supply-chain tooling (M30): license policy, artifact scan, redaction, SBOM, no shells."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "security"))
sys.path.insert(0, str(ROOT / "scripts" / "windows"))

import build_paths  # noqa: E402
import check_licenses  # noqa: E402
import components  # noqa: E402
import sbom  # noqa: E402
import scan_artifacts  # noqa: E402
import verify_sbom  # noqa: E402

POLICY = json.loads((ROOT / "security" / "license-policy.json").read_text("utf-8"))


# -- license policy -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expression", "allowed"),
    [
        ("serde", "MIT OR Apache-2.0", True),
        ("x", "(MIT OR Apache-2.0) AND Unicode-3.0", True),
        ("x", "Apache-2.0  OR  MIT", True),
        ("x", "MIT AND SSPL-1.0", False),
        ("x", "SSPL-1.0 OR MIT", True),  # an allowed alternative may be chosen
        ("x", "GPL-2.0-or-later", False),
        ("ffmpeg", "GPL-2.0-or-later", True),  # ADR-0007 exception
        ("pyinstaller-bootloader", "GPL-2.0-or-later WITH Bootloader-exception", True),
        ("other", "GPL-2.0-or-later WITH Bootloader-exception", False),
        ("openworld-moments-worker", "AGPL-3.0-or-later", True),
        ("someone-else", "AGPL-3.0-or-later", False),
        ("x", "NOASSERTION", False),
        ("x", "", False),
        ("x", "BUSL-1.1", False),
    ],
)
def test_license_expressions(name: str, expression: str, allowed: bool) -> None:
    assert (check_licenses.judge(name, expression, POLICY) is None) is allowed


@pytest.mark.parametrize(
    ("marker", "applies"),
    [
        ("", True),
        ("sys_platform == 'win32'", True),
        ("sys_platform == 'darwin'", False),
        ("platform_python_implementation != 'PyPy'", True),
        ("implementation_name != 'PyPy' and platform_python_implementation != 'PyPy'", True),
        ("sys_platform == 'linux' or sys_platform == 'win32'", True),
        ("python_version < '3.11'", False),
    ],
)
def test_windows_marker_evaluation(marker: str, applies: bool) -> None:
    assert components.marker_applies(marker) is applies


# -- artifact scan and redaction ------------------------------------------------------


def test_artifact_scan_flags_paths_and_secrets_and_stale_exceptions(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "clean.json").write_text('{"version": "1.0"}')
    (release / "log.txt").write_text("built in C:\\Users\\alice\\src with token")
    (release / "key.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    binary = tmp_path / "tool.exe"
    binary.write_bytes(b"\x00\x01/d/a/openworld-moments/openworld-moments/x\x00")
    findings = scan_artifacts.scan([release, binary])
    kinds = {(f["file"], f["kind"]) for f in findings}
    assert kinds == {
        ("release/log.txt", "home-path"),
        ("release/key.pem", "private-key"),
        ("tool.exe", "ci-workspace"),
    }
    exceptions = [
        {"kind": "ci-workspace", "path": "tool.exe", "reason": "test"},
        {"kind": "home-path", "path": "release/never-matches.txt", "reason": "stale"},
    ]
    unexplained, stale = scan_artifacts.judge(findings, exceptions)
    assert {f["kind"] for f in unexplained} == {"home-path", "private-key"}
    assert [s["path"] for s in stale] == ["release/never-matches.txt"]


def test_build_paths_are_redacted_in_every_form() -> None:
    from pathlib import PureWindowsPath

    root = PureWindowsPath(r"D:\a\openworld-moments\openworld-moments")
    text = (
        r"--prefix=/d/a/openworld-moments/openworld-moments/output "
        r"D:\a\openworld-moments\openworld-moments\x D:/a/openworld-moments/openworld-moments/y "
        r"C:\Users\runneradmin\AppData /Users/RUNNER~1/AppData /home/runner/work"
    )
    out = build_paths.redact(text, root)
    assert "openworld-moments/openworld-moments" not in out.replace("\\", "/")
    assert "runneradmin" not in out and "RUNNER~1" not in out and "/home/runner" not in out
    assert out.count("<build-root>") == 3 and "--prefix=<build-root>/output" in out


# -- SBOM -----------------------------------------------------------------------------


def _inventory(runtime: Path) -> dict[str, Any]:
    files = {
        "owm-worker.exe": b"worker",
        "tools/ffmpeg.exe": b"ffmpeg",
        "tools/ffprobe.exe": b"ffprobe",
        "_internal/libcrypto-3-x64.dll": b"openssl",
        "_internal/python312.dll": b"python",
    }
    for name, data in files.items():
        (runtime / name).parent.mkdir(parents=True, exist_ok=True)
        (runtime / name).write_bytes(data)
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return {
        "application": "0.1.0-alpha.29",
        "python": "3.12.14",
        "pyinstaller": "6.22.3",
        "python_build": "20260929",
        "python_notices": {"source_commit": "b" * 40},
        "architecture": "x86_64",
        "commit": "0" * 40,
        "javascript_packages": [
            {"name": "@tauri-apps/api", "versions": ["2.12.4"], "license": "Apache-2.0 OR MIT"}
        ],
        "sources": {
            name: {
                "version": version,
                "url": f"https://example.invalid/{name}",
                "sha256": "c" * 64,
                "license": "GPL-2.0-or-later",
            }
            for name, version in (("ffmpeg", "9.0.2"), ("x264", "d" * 40))
        },
        "tools": [
            {"name": tool, "sha256": digests[f"tools/{tool}.exe"]} for tool in ("ffmpeg", "ffprobe")
        ],
        "files": digests,
    }


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    py = [components.Component("pypi", "fastapi", "0.162.0", "MIT", "pkg:pypi/fastapi@0.162.0")]
    rs = [
        components.Component(
            "cargo", "serde", "1.0.0", "MIT OR Apache-2.0", "pkg:cargo/serde@1.0.0"
        )
    ]
    monkeypatch.setattr(sbom, "python_components", lambda: py)
    monkeypatch.setattr(sbom, "rust_components", lambda: rs)


def test_sbom_is_valid_deterministic_and_complete(stubbed: None, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    inventory = _inventory(runtime)
    first, second = sbom.build(inventory, None), sbom.build(inventory, None)
    assert first == second
    assert verify_sbom.schema_errors(json.dumps(first)) == []
    names = {(c["type"], c["name"]) for c in first["components"]}
    assert {("library", "fastapi"), ("library", "serde"), ("library", "@tauri-apps/api")} <= names
    assert {("application", "ffmpeg"), ("library", "x264"), ("library", "openssl")} <= names
    assert ("application", "cpython") in names and (
        "application",
        "pyinstaller-bootloader",
    ) in names
    models = [c for c in first["components"] if c["type"] == "machine-learning-model"]
    assert {m["name"] for m in models} == {"tiny.en", "base.en"}
    assert all(m["scope"] == "excluded" for m in models)
    files = {
        c["name"]: c["hashes"][0]["content"] for c in first["components"] if c["type"] == "file"
    }
    assert files == {f"runtime/{k}": v for k, v in inventory["files"].items()}
    assert not any(c["name"] == "sqlite" for c in first["components"])  # its proof file is absent
    assert first["metadata"]["component"]["licenses"] == [{"expression": "AGPL-3.0-or-later"}]


def test_verification_catches_drift_tampering_and_bad_checksums(
    stubbed: None, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime"
    inventory = _inventory(runtime)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory))
    release = tmp_path / "release"
    release.mkdir()
    sbom_path = release / "sbom.cdx.json"
    sbom_path.write_text(json.dumps(sbom.build(inventory, None)))
    (release / "notes.txt").write_text("notes")
    (release / "checksums.txt").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in sorted(release.iterdir())
            if p.name != "checksums.txt"
        )
    )
    assert verify_sbom.verify(sbom_path, inventory_path, runtime, release) == []

    (runtime / "tools" / "ffprobe.exe").write_bytes(b"tampered")
    (runtime / "_internal" / "extra.dll").write_bytes(b"x")
    (release / "notes.txt").write_text("changed")
    problems = verify_sbom.verify(sbom_path, inventory_path, runtime, release)
    assert any(p.startswith("package hash") for p in problems)
    assert any(p.startswith("package unlisted") for p in problems)
    assert any("notes.txt does not match" in p for p in problems)

    edited = json.loads(sbom_path.read_text())
    edited["components"] = [c for c in edited["components"] if c["name"] != "serde"]
    sbom_path.write_text(json.dumps(edited))
    assert any(p.startswith("drift") for p in verify_sbom.verify(sbom_path, inventory_path))


# -- user values never become shell commands ------------------------------------------

SHELL_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "getoutput"),
    ("subprocess", "getstatusoutput"),
}


def _python_files() -> list[Path]:
    roots = [
        ROOT / "services/media-worker/openworld_moments",
        ROOT / "packages/contracts/python",
        ROOT / "scripts",
    ]
    return [p for root in roots for p in root.rglob("*.py") if ".venv" not in p.parts]


def test_no_python_code_runs_a_shell() -> None:
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text("utf-8"), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                if pair in SHELL_CALLS or func.attr == "create_subprocess_shell":
                    offenders.append(f"{path}:{node.lineno}")
            for keyword in node.keywords:
                if keyword.arg == "shell" and not (
                    isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                ):
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_desktop_never_spawns_a_shell() -> None:
    rust = "\n".join(
        p.read_text("utf-8") for p in (ROOT / "apps/desktop/src-tauri/src").rglob("*.rs")
    )
    assert not re.search(r'Command::new\(\s*"(?:cmd|cmd\.exe|sh|bash|powershell|pwsh)"', rust)
    manifests = (ROOT / "apps/desktop/src-tauri/Cargo.toml").read_text() + (
        ROOT / "apps/desktop/package.json"
    ).read_text()
    assert "plugin-shell" not in manifests and "tauri-plugin-shell" not in manifests
    frontend = "\n".join(p.read_text("utf-8") for p in (ROOT / "apps/desktop/src").rglob("*.ts*"))
    assert "child_process" not in frontend
