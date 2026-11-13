# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native artifacts on this computer (M34): platform key, architecture and quarantine.

Used before the worker runs an executable it did not build itself (a bundled tool after
verification, or an optional engine the user installed) and before installing an
architecture-specific optional artifact. Only file headers and extended attributes are
read; nothing is executed here.
"""

from __future__ import annotations

import os
import platform
import struct
import sys
from pathlib import Path

#: Mach-O CPU types.
_CPU = {0x01000007: "x86_64", 0x0100000C: "arm64"}
_MH_MAGIC_64 = 0xFEEDFACF
_FAT = {0xCAFEBABE: 20, 0xCAFEBABF: 32}
QUARANTINE = "com.apple.quarantine"


def architecture(machine: str | None = None) -> str:
    """`arm64` or `x86_64` for this Python (the worker binary's own architecture)."""
    value = (machine or platform.machine()).lower()
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    return value or "unknown"


def os_family(sys_platform: str | None = None) -> str:
    value = sys_platform or sys.platform
    if value == "darwin":
        return "macos"
    if value == "win32":
        return "windows"
    return "linux"


def runtime_platform() -> str:
    """`macos-arm64`, `windows-x86_64`, … as used by the model catalog."""
    return f"{os_family()}-{architecture()}"


def compatible(platforms: list[str] | None, current: str | None = None) -> bool:
    """Whether an artifact declared for `platforms` runs here. No declaration = any."""
    if not platforms or "any" in platforms:
        return True
    return (current or runtime_platform()) in platforms


def macho_architectures(path: Path) -> list[str] | None:
    """Architectures of a Mach-O file; `None` when it is not Mach-O (or unreadable)."""
    try:
        with path.open("rb") as stream:
            head = stream.read(8 + 16 * 32)
    except OSError:
        return None
    if len(head) < 8:
        return None
    (little,) = struct.unpack_from("<I", head, 0)
    (big,) = struct.unpack_from(">I", head, 0)
    if little == _MH_MAGIC_64:
        (cpu,) = struct.unpack_from("<I", head, 4)
        return [_CPU.get(cpu, f"cpu-0x{cpu:08x}")]
    if big in _FAT:
        (count,) = struct.unpack_from(">I", head, 4)
        size = _FAT[big]
        if not 0 < count <= 16 or 8 + count * size > len(head):
            return None
        found = []
        for index in range(count):
            (cpu,) = struct.unpack_from(">I", head, 8 + index * size)
            found.append(_CPU.get(cpu, f"cpu-0x{cpu:08x}"))
        return found
    return None


def quarantined(path: Path) -> bool:
    """macOS marks downloaded files with `com.apple.quarantine`; Gatekeeper then checks
    them when they run. The worker reports this instead of running or unquarantining.

    Python's `os.getxattr` is Linux-only, so macOS asks libc directly (read-only)."""
    if sys.platform != "darwin":
        return False
    import ctypes

    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    getxattr = libc.getxattr
    getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    getxattr.restype = ctypes.c_ssize_t
    xattr_nofollow = 0x0001
    size = getxattr(os.fsencode(path), QUARANTINE.encode(), None, 0, 0, xattr_nofollow)
    return bool(size >= 0)


def executable_problem(path: Path, *, sys_platform: str | None = None) -> str | None:
    """Why `path` should not be run on this Mac, in words a user can act on, or `None`.

    Only macOS is checked: a Mach-O built for the other architecture would run under
    Rosetta or not at all, and a quarantined download would be stopped by Gatekeeper.
    The fix is always to install the right build from a trusted source, never to
    remove the quarantine or bypass Gatekeeper.
    """
    if (sys_platform or sys.platform) != "darwin":
        return None
    name = path.name
    if quarantined(path):
        return (
            f"macOS has quarantined {name} as a download. Install it again with its "
            "installer or package manager; OpenWorld Moments does not remove quarantine."
        )
    found = macho_architectures(path)
    if found is not None and architecture() not in found:
        return (
            f"{name} is built for {', '.join(found)}, but this app runs as "
            f"{architecture()}. Install the {architecture()} build of {name}."
        )
    return None
