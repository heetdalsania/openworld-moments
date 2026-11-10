# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fetch immutable source archives; hash before bounded link-free extraction."""

import hashlib
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "packaging"


def extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        if len(members) > 50_000 or sum(m.size for m in members) > 512 * 1024**2:
            raise ValueError("Source archive exceeds limits")
        roots = set()
        for member in members:
            parts = Path(member.name).parts
            if (
                not parts
                or member.name.startswith(("/", "\\"))
                or ".." in parts
                or ":" in member.name
                or "\\" in member.name
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Unsafe source archive member")
            roots.add(parts[0])
        if len(roots) != 1:
            raise ValueError("Expected one source root")
        stream.extractall(target, members=members, filter="data")
    (target / next(iter(roots))).rename(target.with_name(target.name + "-ready"))
    target.rmdir()
    target.with_name(target.name + "-ready").rename(target)


def main() -> None:
    sources = json.loads((ROOT / "scripts/windows/sources.json").read_text())
    archives = OUT / "sources"
    archives.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        destination = archives / source["archive"]
        if not destination.exists():
            with urllib.request.urlopen(source["url"], timeout=60) as response:  # noqa: S310
                raw = response.read(32 * 1024**2 + 1)
            if len(raw) > 32 * 1024**2:
                raise ValueError("Source archive exceeds limits")
            destination.write_bytes(raw)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Source archive checksum mismatch")
        extract(destination, OUT / "source-build" / name)


if __name__ == "__main__":
    main()
