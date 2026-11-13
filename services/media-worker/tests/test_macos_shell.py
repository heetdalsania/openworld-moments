# SPDX-License-Identifier: AGPL-3.0-or-later
"""M33: the macOS shell checks read Mach-O headers and bundles correctly on any OS."""

from __future__ import annotations

import importlib.util
import json
import plistlib
import shutil
import struct
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARM64, X86_64 = 0x0100000C, 0x01000007


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


macho = _load("macho", ROOT / "scripts/macos/macho.py")
shell = _load("build_shell", ROOT / "scripts/macos/build-shell.py")


def thin(cpu: int, minos: tuple[int, int, int] | None = (14, 0, 0), old: bool = False) -> bytes:
    """A minimal 64-bit Mach-O header with an optional minimum-OS load command."""
    commands = b""
    if minos is not None:
        packed = (minos[0] << 16) | (minos[1] << 8) | minos[2]
        if old:  # LC_VERSION_MIN_MACOSX
            commands = struct.pack("<IIII", 0x24, 16, packed, packed)
        else:  # LC_BUILD_VERSION, platform macOS, no tools
            commands = struct.pack("<IIIIII", 0x32, 24, 1, packed, packed, 0)
    # A non-version command first, to prove the walker skips it.
    commands = struct.pack("<II", 0x2, 16) + b"\0" * 8 + commands
    count = 2 if minos is not None else 1
    header = struct.pack("<IiIIIIII", 0xFEEDFACF, cpu, 0, 2, count, len(commands), 0, 0)
    return header + commands


def fat(*slices: bytes) -> bytes:
    table, body = b"", b""
    offset = 8 + 20 * len(slices)
    for data in slices:
        (cpu,) = struct.unpack_from("<i", data, 4)
        table += struct.pack(">iiIII", cpu, 0, offset + len(body), len(data), 0)
        body += data
    return struct.pack(">II", 0xCAFEBABE, len(slices)) + table + body


def test_thin_binaries_report_architecture_and_minimum() -> None:
    assert macho.slices(thin(ARM64)) == [macho.Slice("arm64", "14.0")]
    assert macho.slices(thin(X86_64, (13, 5, 1))) == [macho.Slice("x86_64", "13.5.1")]
    assert macho.slices(thin(X86_64, (10, 15, 0), old=True)) == [macho.Slice("x86_64", "10.15")]
    assert macho.slices(thin(ARM64, None)) == [macho.Slice("arm64", None)]


def test_universal_binaries_list_every_slice() -> None:
    found = macho.slices(fat(thin(X86_64), thin(ARM64)))
    assert [s.arch for s in found] == ["x86_64", "arm64"]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"MZ\x90\x00" + b"\0" * 60,  # a Windows executable
        thin(ARM64)[:20],  # truncated header
        thin(ARM64)[:40],  # load commands cut off
        struct.pack("<IiIIIIII", 0xFEEDFACF, ARM64, 0, 2, 1, 8, 0, 0) + struct.pack("<II", 1, 4),
        struct.pack(">II", 0xCAFEBABE, 0),  # no slices
        struct.pack(">II", 0xCAFEBABE, 3) + b"\0" * 10,  # truncated table
    ],
)
def test_malformed_input_is_rejected_not_trusted(data: bytes) -> None:
    with pytest.raises(macho.MachOError):
        macho.slices(data)


def test_native_check_rejects_wrong_arch_universal_and_newer_minimum(tmp_path: Path) -> None:
    def check(data: bytes) -> list[str]:
        path = tmp_path / "bin"
        path.write_bytes(data)
        problems: list[str] = macho.check_native(path, "arm64", "14.0")
        return problems

    assert check(thin(ARM64)) == []
    assert check(thin(ARM64, (11, 0, 0))) == []  # older minimum still runs on 14
    assert "built for x86_64" in check(thin(X86_64))[0]
    assert "universal binary" in check(fat(thin(ARM64), thin(X86_64)))[0]
    assert "above the 14.0 floor" in check(thin(ARM64, (15, 0, 0)))[0]
    assert "no minimum" in check(thin(ARM64, None))[0]
    assert "not a 64-bit Mach-O" in check(b"#!/bin/sh\necho hi\n")[0]


def test_is_macho_only_matches_mach_o_magic(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(thin(ARM64))
    (tmp_path / "b").write_bytes(fat(thin(ARM64)))
    (tmp_path / "c").write_bytes(b"{}")
    (tmp_path / "d").write_bytes(b"")
    assert [macho.is_macho(tmp_path / n) for n in "abcd"] == [True, True, False, False]
    assert not macho.is_macho(tmp_path / "missing")


def make_app(
    tmp_path: Path,
    exe: bytes,
    minimum: str = "14.0",
    extra: dict[str, bytes] | None = None,
) -> Path:
    app = tmp_path / "OpenWorld Moments.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    info = {
        "CFBundleExecutable": "openworld-moments-desktop",
        "LSMinimumSystemVersion": minimum,
        "NSLocalNetworkUsageDescription": "Receive explicitly enabled phone uploads.",
    }
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    (app / "Contents" / "MacOS" / "openworld-moments-desktop").write_bytes(exe)
    (app / "Contents" / "Resources" / "icon.icns").write_bytes(b"icns")
    for name, data in (extra or {}).items():
        (app / "Contents" / name).parent.mkdir(parents=True, exist_ok=True)
        (app / "Contents" / name).write_bytes(data)
    return app


def test_bundle_verification_accepts_a_native_shell(tmp_path: Path) -> None:
    assert shell.verify_bundle(make_app(tmp_path, thin(ARM64)), "arm64") == []


@pytest.mark.parametrize(
    ("exe", "minimum", "extra", "expected"),
    [
        (thin(X86_64), "14.0", None, "built for x86_64"),
        (thin(ARM64), "13.0", None, "LSMinimumSystemVersion"),
        (thin(ARM64, (11, 0, 0)), "14.0", None, "MACOSX_DEPLOYMENT_TARGET"),
        (fat(thin(ARM64), thin(X86_64)), "14.0", None, "universal"),
        (thin(ARM64), "14.0", {"Frameworks/libx.dylib": thin(X86_64)}, "libx.dylib"),
        (b"not a binary", "14.0", None, "not a Mach-O"),
    ],
)
def test_bundle_verification_names_each_problem(
    tmp_path: Path, exe: bytes, minimum: str, extra: dict[str, bytes] | None, expected: str
) -> None:
    problems = shell.verify_bundle(make_app(tmp_path, exe, minimum, extra), "arm64")
    assert any(expected in p for p in problems), problems


def test_bundle_without_info_plist_or_executable_is_rejected(tmp_path: Path) -> None:
    app = make_app(tmp_path, thin(ARM64))
    (app / "Contents" / "MacOS" / "openworld-moments-desktop").unlink()
    assert "CFBundleExecutable" in shell.verify_bundle(app, "arm64")[-1]
    (app / "Contents" / "Info.plist").unlink()
    assert "Info.plist" in shell.verify_bundle(app, "arm64")[0]


FIXTURES = ROOT / "packages/contracts/fixtures/platform-capabilities/valid"


def test_version_report_check_matches_the_contract_fixtures() -> None:
    def report(name: str) -> dict[str, object]:
        return dict(json.loads((FIXTURES / name).read_text("utf-8")))

    assert shell.check_report(report("macos-apple-silicon.json"), "arm64") == []
    assert shell.check_report(report("macos-intel.json"), "x86_64") == []
    assert shell.check_report(report("macos-apple-silicon.json"), "x86_64")
    rosetta = shell.check_report(report("macos-under-rosetta.json"), "x86_64")
    assert any("not running natively" in p for p in rosetta)
    assert shell.check_report(report("windows-alpha.json"), "x86_64")
    shell_only = report("macos-apple-silicon.json")
    shell_only["build"] = {**shell_only["build"], "bundled_worker": False}  # type: ignore[dict-item]
    assert shell.check_report(shell_only, "arm64", bundled=False) == []
    assert any("bundled_worker" in p for p in shell.check_report(shell_only, "arm64"))
    debug = shell.check_report(report("macos-debug-below-floor.json"), "arm64")
    assert any("build" in p for p in debug)
    assert shell.check_report({}, "arm64")


def test_artifact_names_are_plain_and_architecture_specific() -> None:
    name = shell.artifact_name("0.1.0-alpha.33", "arm64", "0123456789abcdef")
    assert name == "OpenWorld-Moments_0.1.0-alpha.33+0123456_macOS_arm64_unsigned-dev.zip"
    assert "x86_64" in shell.artifact_name("0.0.0", "x86_64", "abcdef0")
    assert shell.artifact_name("../../x y", "arm64", "zz") == (
        "OpenWorld-Moments_....xy+unknown_macOS_arm64_unsigned-dev.zip"
    )
    with pytest.raises(ValueError, match="architecture"):
        shell.artifact_name("0.0.0", "universal", "abc")


def test_floor_matches_the_host_and_the_tauri_configuration() -> None:
    config = json.loads((ROOT / "apps/desktop/src-tauri/tauri.macos.conf.json").read_text())
    assert config["bundle"]["macOS"]["minimumSystemVersion"] == shell.FLOOR
    platform_rs = (ROOT / "apps/desktop/src-tauri/src/platform/mod.rs").read_text("utf-8")
    assert f'pub const MACOS_MINIMUM: &str = "{shell.FLOOR}";' in platform_rs


# -- M34: library dependencies and the bundled runtime --------------------------------------


def with_dylibs(cpu: int, dylibs: list[str], rpaths: list[str] = ()) -> bytes:  # type: ignore[assignment]
    """A thin Mach-O with LC_BUILD_VERSION, LC_LOAD_DYLIB and LC_RPATH commands."""

    def string_command(cmd: int, text: str, offset: int) -> bytes:
        raw = text.encode() + b"\0"
        size = (offset + len(raw) + 7) // 8 * 8
        head = struct.pack("<III", cmd, size, offset) + b"\0" * (offset - 12)
        return (head + raw).ljust(size, b"\0")

    commands = struct.pack("<IIIIII", 0x32, 24, 1, 14 << 16, 14 << 16, 0)
    commands += b"".join(string_command(0xC, d, 24) for d in dylibs)
    commands += b"".join(string_command(0x8000001C, r, 12) for r in rpaths)
    count = 1 + len(dylibs) + len(rpaths)
    return struct.pack("<IiIIIIII", 0xFEEDFACF, cpu, 0, 2, count, len(commands), 0, 0) + commands


def test_load_commands_report_dylibs_and_rpaths() -> None:
    data = with_dylibs(
        ARM64,
        ["/usr/lib/libSystem.B.dylib", "@rpath/libpython3.12.dylib"],
        ["@loader_path/_internal"],
    )
    (found,) = macho.slices(data)
    assert found.dylibs == ("/usr/lib/libSystem.B.dylib", "@rpath/libpython3.12.dylib")
    assert found.rpaths == ("@loader_path/_internal",)
    bad = bytearray(data)
    struct.pack_into("<I", bad, 32 + 24 + 8, 4)  # name offset inside the header
    with pytest.raises(macho.MachOError, match="string"):
        macho.slices(bytes(bad))


def runtime_tree(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    (root / "_internal").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "owm-worker").write_bytes(
        with_dylibs(
            ARM64,
            ["/usr/lib/libSystem.B.dylib", "@rpath/libpython3.12.dylib"],
            ["@loader_path/_internal"],
        )
    )
    (root / "_internal/libpython3.12.dylib").write_bytes(
        with_dylibs(
            ARM64,
            [
                "/usr/lib/libz.1.dylib",
                "/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation",
            ],
        )
    )
    (root / "_internal/ext.so").write_bytes(
        with_dylibs(ARM64, ["@loader_path/libpython3.12.dylib"])
    )
    (root / "tools/ffmpeg").write_bytes(with_dylibs(ARM64, ["/usr/lib/libSystem.B.dylib"]))
    (root / "data.json").write_text("{}")
    return root


def test_runtime_audit_accepts_system_and_bundled_libraries(tmp_path: Path) -> None:
    root = runtime_tree(tmp_path)
    problems, summary = macho.audit_runtime(root, "arm64", "14.0")
    assert problems == []
    assert summary["macho_files"] == 4 and summary["newest_minimum"] == "14.0"
    assert "/usr/lib/libz.1.dylib" in summary["system_libraries"]


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        (
            "_internal/brew.so",
            with_dylibs(ARM64, ["/opt/homebrew/lib/libssl.3.dylib"]),
            "not in the runtime",
        ),
        (
            "_internal/missing.so",
            with_dylibs(ARM64, ["@loader_path/gone.dylib"]),
            "not in the runtime",
        ),
        ("_internal/rpath.so", with_dylibs(ARM64, ["@rpath/libx.dylib"]), "not in the runtime"),
        (
            "_internal/escape.so",
            with_dylibs(ARM64, ["@loader_path/../../outside.dylib"]),
            "not in the runtime",
        ),
        ("_internal/intel.so", with_dylibs(X86_64, []), "built for x86_64"),
        ("_internal/fat.so", fat(thin(ARM64), thin(X86_64)), "universal"),
    ],
)
def test_runtime_audit_names_each_problem(
    tmp_path: Path, name: str, data: bytes, expected: str
) -> None:
    root = runtime_tree(tmp_path)
    (tmp_path / "outside.dylib").write_bytes(thin(ARM64))
    (root / name).write_bytes(data)
    problems, _ = macho.audit_runtime(root, "arm64", "14.0")
    assert any(name in p and expected in p for p in problems), problems


def test_runtime_audit_rejects_links_out_of_the_runtime(tmp_path: Path) -> None:
    root = runtime_tree(tmp_path)
    (tmp_path / "secret").write_text("x")
    (root / "_internal/link").symlink_to(tmp_path / "secret")
    (root / "_internal/ok").symlink_to(root / "data.json")
    problems, _ = macho.audit_runtime(root, "arm64", "14.0")
    assert problems == ["_internal/link: link points outside the runtime"]


def test_packaged_bundle_requires_a_complete_runtime(tmp_path: Path) -> None:
    app = make_app(tmp_path, thin(ARM64))
    assert shell.verify_bundle(app, "arm64") == []
    missing = shell.verify_bundle(app, "arm64", require_runtime=True)
    assert any("worker is not bundled" in p for p in missing)
    runtime = runtime_tree(tmp_path / "frozen")
    shutil.copytree(runtime, app / "Contents/Resources/runtime")
    incomplete = shell.verify_bundle(app, "arm64", require_runtime=True)
    assert "runtime/tools/ffprobe: missing" in incomplete
    (app / "Contents/Resources/runtime/tools/ffprobe").write_bytes(with_dylibs(ARM64, []))
    (app / "Contents/Resources/runtime/inventory.json").write_text("{}")
    assert shell.verify_bundle(app, "arm64", require_runtime=True) == []
    (app / "Contents/Resources/runtime/_internal/brew.so").write_bytes(
        with_dylibs(ARM64, ["/opt/homebrew/lib/libssl.3.dylib"])
    )
    assert any("brew.so" in p for p in shell.verify_bundle(app, "arm64", require_runtime=True))


def test_runtime_must_match_the_build_architecture(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    assert "freeze-worker" in str(shell.runtime_problem("arm64", runtime))
    runtime.mkdir()
    for doc, problem in (
        ({"platform": "macos", "architecture": "arm64"}, None),
        ({"platform": "macos", "architecture": "x86_64"}, "not macos/arm64"),
        ({"architecture": "x86_64"}, "not macos/arm64"),
    ):
        (runtime / "inventory.json").write_text(json.dumps(doc))
        result = shell.runtime_problem("arm64", runtime)
        assert (problem is None and result is None) or (problem and problem in str(result))


def test_missing_local_network_purpose_is_rejected(tmp_path: Path) -> None:
    app = make_app(tmp_path, thin(ARM64))
    info_path = app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    del info["NSLocalNetworkUsageDescription"]
    info_path.write_bytes(plistlib.dumps(info))
    assert "Info.plist: NSLocalNetworkUsageDescription is missing" in shell.verify_bundle(
        app, "arm64"
    )
    source = plistlib.loads((ROOT / "apps/desktop/src-tauri/Info.plist").read_bytes())
    assert "temporary phone upload" in source["NSLocalNetworkUsageDescription"]
