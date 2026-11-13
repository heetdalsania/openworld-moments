# SPDX-License-Identifier: AGPL-3.0-or-later
"""M34: native artifacts are checked for architecture and quarantine before they run."""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Any

import pytest

from openworld_moments import native

ARM64, X86_64 = 0x0100000C, 0x01000007


def thin(cpu: int) -> bytes:
    return struct.pack("<IiIIIIII", 0xFEEDFACF, cpu, 0, 2, 0, 0, 0, 0)


def fat(*cpus: int) -> bytes:
    table = b"".join(struct.pack(">iiIII", cpu, 0, 4096, 32, 12) for cpu in cpus)
    return struct.pack(">II", 0xCAFEBABE, len(cpus)) + table


@pytest.mark.parametrize(
    ("machine", "expected"),
    [("arm64", "arm64"), ("aarch64", "arm64"), ("AMD64", "x86_64"), ("x86_64", "x86_64")],
)
def test_architecture_names_are_normalised(machine: str, expected: str) -> None:
    assert native.architecture(machine) == expected


def test_platform_keys_and_compatibility() -> None:
    assert native.os_family("darwin") == "macos"
    assert native.os_family("win32") == "windows"
    assert native.os_family("linux") == "linux"
    here = native.runtime_platform()
    assert native.compatible(None)
    assert native.compatible(["any"])
    assert native.compatible([here, "linux-arm64"])
    assert not native.compatible(["linux-arm64"], current="macos-arm64")
    assert native.compatible(["macos-arm64"], current="macos-arm64")


def test_macho_headers_are_read_without_running_anything(tmp_path: Path) -> None:
    cases = {
        "arm": (thin(ARM64), ["arm64"]),
        "intel": (thin(X86_64), ["x86_64"]),
        "universal": (fat(X86_64, ARM64), ["x86_64", "arm64"]),
        "script": (b"#!/bin/sh\necho hi\n", None),
        "pe": (b"MZ" + b"\0" * 62, None),
        "empty": (b"", None),
        "bad-fat": (struct.pack(">II", 0xCAFEBABE, 40), None),
    }
    for name, (data, expected) in cases.items():
        (tmp_path / name).write_bytes(data)
        assert native.macho_architectures(tmp_path / name) == expected, name
    assert native.macho_architectures(tmp_path / "missing") is None


def test_wrong_architecture_is_explained(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(native, "architecture", lambda machine=None: "arm64")
    monkeypatch.setattr(native, "quarantined", lambda path: False)
    (tmp_path / "whisper-cli").write_bytes(thin(X86_64))
    problem = native.executable_problem(tmp_path / "whisper-cli", sys_platform="darwin")
    assert problem is not None
    assert "built for x86_64" in problem and "Install the arm64 build" in problem
    (tmp_path / "tesseract").write_bytes(fat(X86_64, ARM64))
    assert native.executable_problem(tmp_path / "tesseract", sys_platform="darwin") is None
    (tmp_path / "script").write_bytes(b"#!/bin/sh\n")
    assert native.executable_problem(tmp_path / "script", sys_platform="darwin") is None
    # Other systems are not checked (Windows behavior unchanged).
    assert native.executable_problem(tmp_path / "whisper-cli", sys_platform="win32") is None


def test_quarantined_download_is_refused_not_unquarantined(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(native, "quarantined", lambda path: True)
    tool = tmp_path / "whisper-cli"
    tool.write_bytes(thin(ARM64))
    problem = native.executable_problem(tool, sys_platform="darwin")
    assert problem is not None and "quarantined" in problem
    assert "does not remove quarantine" in problem


@pytest.mark.skipif(sys.platform != "darwin", reason="extended attributes are macOS-specific")
def test_real_quarantine_attribute_is_detected(tmp_path: Path) -> None:
    import subprocess

    tool = tmp_path / "tool ✓"
    tool.write_bytes(thin(ARM64))
    assert not native.quarantined(tool)
    xattr = ["/usr/bin/xattr"]
    write = [*xattr, "-w", native.QUARANTINE, "0081;00000000;Test;", str(tool)]
    subprocess.run(write, check=True)  # noqa: S603 - the system xattr tool, fixed arguments
    assert native.quarantined(tool)
    problem = native.executable_problem(tool)
    assert problem is not None and "quarantined" in problem
    remove = [*xattr, "-d", native.QUARANTINE, str(tool)]
    subprocess.run(remove, check=True)  # noqa: S603 - the system xattr tool, fixed arguments
    assert not native.quarantined(tool)
    assert not native.quarantined(tmp_path / "missing")
