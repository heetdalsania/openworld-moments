# SPDX-License-Identifier: AGPL-3.0-or-later
"""The packaged Windows version, read from one place (M32).

`apps/desktop/src-tauri/tauri.packaged.conf.json` is the single source of the
installer version. Packaging, the native smoke test and release verification read
it here instead of repeating the string, so a release bump is a one-line change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path("apps/desktop/src-tauri/tauri.packaged.conf.json")
# Alpha releases only: M32 publishes 0.1.0-alpha.N; a stable or beta number needs a
# deliberate change here and in the release documentation.
VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-alpha\.(0|[1-9]\d*)$")


def packaged_version(root: Path = ROOT) -> str:
    """Return the validated installer version from the packaged Tauri overlay."""
    data = json.loads((root / CONFIG).read_text("utf-8"))
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError(f"Packaged version must look like 0.1.0-alpha.N, got {version!r}")
    return version


def installer_name(version: str) -> str:
    """The public installer file name inside the release set."""
    return f"OpenWorld-Moments_{version}_Windows_x64-setup.exe"


def upgrade_test_version(version: str) -> str:
    """The test-only higher version used to exercise in-place upgrades (never shipped)."""
    return f"{version}.1"
