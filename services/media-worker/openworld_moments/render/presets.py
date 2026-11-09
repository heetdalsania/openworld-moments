# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render presets: contributed JSON files validated against the render-preset contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openworld_moments_contracts import ContractError, load, normalize

from openworld_moments.render.plan import RenderError
from openworld_moments.resources import data_root

DEFAULT_PRESETS = data_root() / "presets/render"
MAX_PRESET_BYTES = 64 * 1024


class PresetCatalog:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else DEFAULT_PRESETS

    def _read(self, path: Path) -> dict[str, Any] | None:
        """A preset that is not a regular, bounded, valid file is skipped, not trusted."""
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PRESET_BYTES:
                return None
            doc = normalize(load("render-preset", json.loads(path.read_text("utf-8"))))
        except (OSError, ValueError, ContractError):
            return None
        if doc["id"] != path.stem or doc["video"]["codec"] != "h264":
            return None
        return dict(doc)

    def all(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        presets = (self._read(p) for p in sorted(self.directory.glob("*.json")))
        return [p for p in presets if p is not None]

    def get(self, preset_id: str) -> dict[str, Any]:
        for preset in self.all():
            if preset["id"] == preset_id:
                return preset
        raise RenderError("render.unknown_preset", "That render preset is not installed.")
