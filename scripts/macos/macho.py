# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the architecture and minimum macOS version of a Mach-O file (M33).

Pure Python, so CI and tests do not depend on `lipo`, `otool` or `vtool`, and the same
checks run on any machine. Only the headers are read; nothing is executed.

* thin 64-bit Mach-O (`MH_MAGIC_64`): one architecture;
* universal ("fat") files: every slice is listed, so a native-only check can reject them;
* the minimum OS comes from `LC_BUILD_VERSION` (or the older `LC_VERSION_MIN_MACOSX`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
PLATFORM_MACOS = 1
CPU = {0x01000007: "x86_64", 0x0100000C: "arm64"}
HEADER = 32
MAX_COMMANDS = 4096


class MachOError(ValueError):
    """Not a Mach-O file, or a malformed one."""


@dataclass(frozen=True)
class Slice:
    arch: str
    minimum: str | None  # "14.0", or None when the binary declares no macOS minimum


def _version(value: int) -> str:
    major, minor, patch = value >> 16, (value >> 8) & 0xFF, value & 0xFF
    return f"{major}.{minor}" + (f".{patch}" if patch else "")


def _thin(data: bytes, offset: int = 0) -> Slice:
    if len(data) < offset + 4 or struct.unpack_from("<I", data, offset)[0] != MH_MAGIC_64:
        raise MachOError("not a 64-bit Mach-O")
    if len(data) < offset + HEADER:
        raise MachOError("truncated header")
    magic, cputype, _sub, _type, ncmds, sizeofcmds = struct.unpack_from("<IiIIII", data, offset)
    if magic != MH_MAGIC_64:
        raise MachOError("not a 64-bit Mach-O")
    arch = CPU.get(cputype & 0xFFFFFFFF, f"cpu-0x{cputype & 0xFFFFFFFF:08x}")
    if ncmds > MAX_COMMANDS or offset + HEADER + sizeofcmds > len(data):
        raise MachOError("load commands out of range")
    minimum: str | None = None
    cursor, end = offset + HEADER, offset + HEADER + sizeofcmds
    for _ in range(ncmds):
        if cursor + 8 > end:
            raise MachOError("truncated load command")
        cmd, size = struct.unpack_from("<II", data, cursor)
        if size < 8 or cursor + size > end:
            raise MachOError("bad load command size")
        if cmd == LC_BUILD_VERSION and size >= 16:
            platform, minos = struct.unpack_from("<II", data, cursor + 8)
            if platform == PLATFORM_MACOS:
                minimum = _version(minos)
        elif cmd == LC_VERSION_MIN_MACOSX and size >= 16 and minimum is None:
            (version,) = struct.unpack_from("<I", data, cursor + 8)
            minimum = _version(version)
        cursor += size
    return Slice(arch, minimum)


def slices(data: bytes) -> list[Slice]:
    """Every architecture in `data`: one for a thin file, several for a universal one."""
    if len(data) < 8:
        raise MachOError("too small")
    (magic,) = struct.unpack_from(">I", data, 0)
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        (count,) = struct.unpack_from(">I", data, 4)
        if count == 0 or count > 16:
            raise MachOError("bad slice count")
        entry = 32 if magic == FAT_MAGIC_64 else 20
        found = []
        for index in range(count):
            base = 8 + index * entry
            if base + entry > len(data):
                raise MachOError("truncated slice table")
            if magic == FAT_MAGIC_64:
                _cpu, _sub, offset, _size = struct.unpack_from(">iiQQ", data, base)
            else:
                _cpu, _sub, offset, _size = struct.unpack_from(">iiII", data, base)
            found.append(_thin(data, offset))
        return found
    return [_thin(data)]


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            head = stream.read(4)
    except OSError:
        return False
    if len(head) < 4:
        return False
    return struct.unpack("<I", head)[0] == MH_MAGIC_64 or struct.unpack(">I", head)[0] in (
        FAT_MAGIC,
        FAT_MAGIC_64,
    )


def read(path: Path) -> list[Slice]:
    return slices(path.read_bytes())


def release(text: str) -> tuple[int, int, int]:
    parts = [int(p) for p in text.split(".")] + [0, 0]
    return parts[0], parts[1], parts[2]


def check_native(path: Path, arch: str, floor: str) -> list[str]:
    """Problems that stop `path` shipping as a native `arch` binary for macOS `floor`+."""
    try:
        found = read(path)
    except (OSError, MachOError) as error:
        return [f"{path.name}: {error}"]
    problems = []
    if len(found) != 1:
        problems.append(f"{path.name}: universal binary ({', '.join(s.arch for s in found)})")
    for item in found:
        if item.arch != arch:
            problems.append(f"{path.name}: built for {item.arch}, expected {arch}")
        if item.minimum is None:
            problems.append(f"{path.name}: declares no minimum macOS version")
        elif release(item.minimum) > release(floor):
            problems.append(f"{path.name}: needs macOS {item.minimum}, above the {floor} floor")
    return problems
