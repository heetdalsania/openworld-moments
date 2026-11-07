# SPDX-License-Identifier: AGPL-3.0-or-later
"""Media-free local ROI overrides. Installed catalog files are never written."""

from __future__ import annotations

import contextlib
from types import MappingProxyType
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.errors import ContractError

from openworld_moments.detectors.example import BrightRegion
from openworld_moments.detectors.profiles import (
    ProfileCatalog,
    ProfileError,
    ResolvedProfile,
    canonical,
    digest,
)
from openworld_moments.detectors.sdk import AnalysisContext, Frame
from openworld_moments.storage import Database, SettingsRepository, transaction, utc_now

PREFIX = "calibration.roi.v1."


def validate_patch(value: Any) -> dict[str, Any]:
    try:
        if len(canonical(value).encode()) > 65536:
            raise ProfileError(["patch: exceeds 64 KiB"])
        return normalize(load("profile-patch", value))
    except ContractError as exc:
        raise ProfileError(exc.issues) from exc
    except (ValueError, RecursionError) as exc:
        raise ProfileError(["patch: expected finite JSON data"]) from exc


def apply_patch(catalog: ProfileCatalog, base: ResolvedProfile, patch: Any) -> ResolvedProfile:
    patch = validate_patch(patch)
    doc = base.document()
    if patch["profile_id"] != doc["id"] or patch["game_family"] != doc["game_family"]:
        raise ProfileError(["patch: profile identity or game family is incompatible"])
    if patch["frame"] != doc["frame"]:
        raise ProfileError(
            ["patch.frame: compatibility changed; review and save against the new base"]
        )
    doc["regions"].update(patch["regions"])
    # Already resolved: don't merge inheritance again. Preserve the original base key.
    doc.pop("extends", None)
    resolved = catalog.resolve(doc)
    return ResolvedProfile(resolved.json, digest([base.key, patch["regions"]]))


class Calibration:
    def __init__(self, database: Database, catalog: ProfileCatalog | None = None) -> None:
        self.database = database
        self.catalog = catalog or ProfileCatalog()

    def patch(self, profile_id: str) -> Any:
        with contextlib.closing(self.database.connect()) as conn:
            return SettingsRepository(conn).get(PREFIX + profile_id)

    def effective(self, profile_id: str) -> ResolvedProfile:
        base = self.catalog.load(profile_id)
        patch = self.patch(profile_id)
        return apply_patch(self.catalog, base, patch) if patch else base

    def state(self, profile_id: str) -> dict[str, Any]:
        base = self.catalog.load(profile_id)
        patch = self.patch(profile_id)
        conflict = None
        effective = base
        if patch:
            try:
                effective = apply_patch(self.catalog, base, patch)
            except ProfileError as exc:
                conflict = exc.message
        return {
            "base": base.document(),
            "base_key": base.key,
            "effective": effective.document(),
            "patch": patch,
            "base_changed": bool(patch and patch["base_key"] != base.key),
            "conflict": conflict,
        }

    def save(self, profile_id: str, base_key: str, regions: dict[str, Any]) -> dict[str, Any]:
        base = self.catalog.load(profile_id)
        if base_key != base.key:
            raise ProfileError(["base_key: profile changed; reload before saving"])
        doc = base.document()
        # Overrides are sparse; unedited defaults track future base updates.
        patch = validate_patch(
            {
                "schema_version": "1.10",
                "profile_id": profile_id,
                "base_version": doc["profile_version"],
                "base_key": base.key,
                "game_family": doc["game_family"],
                "frame": doc["frame"],
                "regions": {
                    name: value
                    for name, value in regions.items()
                    if value != doc["regions"].get(name)
                },
                "provenance": {"tool": "owm-calibration", "version": "1", "created_at": utc_now()},
            }
        )
        apply_patch(self.catalog, base, patch)
        self._store(profile_id, patch)
        return self.state(profile_id)

    def import_patch(self, profile_id: str, value: Any) -> dict[str, Any]:
        patch = validate_patch(value)
        apply_patch(self.catalog, self.catalog.load(profile_id), patch)
        self._store(profile_id, patch)
        return self.state(profile_id)

    def reset(self, profile_id: str) -> dict[str, Any]:
        self.catalog.load(profile_id)
        self._store(profile_id, None)
        return self.state(profile_id)

    def _store(self, profile_id: str, patch: Any) -> None:
        with contextlib.closing(self.database.connect()) as conn, transaction(conn):
            SettingsRepository(conn).set(PREFIX + profile_id, patch)

    def preview(
        self,
        profile_id: str,
        base_key: str,
        regions: dict[str, Any],
        gray: list[int],
        source_ms: int,
    ) -> dict[str, Any]:
        """One bounded, ephemeral sample through the shipped SDK. Never writes events."""
        base = self.catalog.load(profile_id)
        if base.key != base_key:
            raise ProfileError(["base_key: profile changed; reload before previewing"])
        if len(gray) != 2304 or any(type(p) is not int or not 0 <= p <= 255 for p in gray):
            raise ProfileError(["gray: expected one 64 by 36 grayscale sample"])
        doc = base.document()
        doc["regions"].update(regions)
        doc.pop("extends", None)
        doc = self.catalog.resolve(doc).document()
        setting = next(
            (s for s in doc["detectors"] if s["id"] == BrightRegion.id and s["enabled"]), None
        )
        if setting is None:
            return {
                "available": False,
                "message": "No single-frame built-in preview is available for this profile.",
            }
        if "signal" not in doc["regions"]:
            raise ProfileError(["regions.signal: required for this built-in"])
        detector = BrightRegion()
        context = AnalysisContext(
            asset_id="calibration-preview",
            duration_ms=source_ms + 500,
            frames=(Frame(source_ms, 64, 36, bytes(gray)),),
            regions=MappingProxyType({name: tuple(r) for name, r in doc["regions"].items()}),
            settings=MappingProxyType(setting),
            vocabulary=MappingProxyType({}),
            check_cancelled=lambda: None,
            progress=lambda *_: None,
        )
        try:
            detector.setup(context)
            detections = [
                {
                    "type": d.type,
                    "start_ms": d.start_ms,
                    "end_ms": d.end_ms,
                    "confidence": d.confidence,
                    "evidence": [dict(e) for e in d.evidence],
                }
                for d in detector.detect(context)
            ]
        finally:
            detector.close()
        return {
            "available": True,
            "detector_id": detector.id,
            "detector_version": detector.version,
            "sample_count": 1,
            "confirmation_frames": setting.get("confirmation_frames", 3),
            "detections": detections,
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = []
        if self.catalog.root.is_dir():
            for path in sorted(self.catalog.root.iterdir())[:128]:
                if not path.is_dir() or not (path / "profile.json").is_file():
                    continue
                try:
                    doc = self.catalog.load(path.name).document()
                    rows.append(
                        {
                            "id": doc["id"],
                            "display_name": doc["display_name"],
                            "profile_version": doc["profile_version"],
                        }
                    )
                except ProfileError:
                    # One broken installed manifest cannot hide the rest of the catalog.
                    rows.append(
                        {"id": path.name, "display_name": path.name, "profile_version": "invalid"}
                    )
        return rows
