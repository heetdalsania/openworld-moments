# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded local JSON catalog. Profiles are data, never Python/plugin imports."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize
from openworld_moments_contracts.errors import ContractError

from openworld_moments.detectors.sdk import AnalysisError

SLUG = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
DEFAULT_CATALOG = Path(__file__).resolve().parents[4] / "profiles"
MAX_PROFILE_BYTES = 256 * 1024
MAX_INHERITANCE = 8


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ProfileError(AnalysisError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("profile.invalid", "; ".join(issues))
        self.issues = issues


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            raise ValueError("expected a regular manifest file")
        with path.open("rb") as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
        if len(raw) > MAX_PROFILE_BYTES:
            raise ValueError("profile exceeds 256 KiB")
        doc = json.loads(raw, object_pairs_hook=_pairs)
        if not isinstance(doc, dict):
            raise ValueError("expected a JSON object")
        canonical(doc)  # rejects NaN and Infinity
        return doc
    except (OSError, ValueError, RecursionError) as exc:
        raise ProfileError(["(root): cannot read a bounded, valid JSON manifest"]) from exc


@dataclass(frozen=True)
class ResolvedProfile:
    # Private JSON snapshot; a consumer always receives an independent document.
    json: str
    key: str

    def document(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.json)
        return result


class ProfileCatalog:
    def __init__(self, root: Path = DEFAULT_CATALOG) -> None:
        self.root = root.resolve()

    def path(self, profile_id: str) -> Path:
        if not SLUG.fullmatch(profile_id):
            raise ProfileError(["id: expected a profile slug"])
        path = self.root / profile_id / "profile.json"
        if not path.resolve().is_relative_to(self.root):
            raise ProfileError(["id: profile path leaves the catalog"])
        return path

    def load(self, profile_id: str) -> ResolvedProfile:
        return self.resolve(read_manifest(self.path(profile_id)), (profile_id,))

    def resolve(self, doc: dict[str, Any], chain: tuple[str, ...] = ()) -> ResolvedProfile:
        doc = copy.deepcopy(doc)
        if len(chain) > MAX_INHERITANCE:
            raise ProfileError(["extends: inheritance exceeds 8 profiles"])
        if chain and doc.get("id") != chain[-1]:
            raise ProfileError(["id: does not match the catalog directory"])
        parent = doc.get("extends")
        lineage: list[str] = []
        if parent is not None:
            if not isinstance(parent, str) or not SLUG.fullmatch(parent):
                raise ProfileError(["extends: expected a catalog profile slug"])
            if parent in chain:
                raise ProfileError(["extends: inheritance cycle"])
            base = self.resolve(read_manifest(self.path(parent)), (*chain, parent))
            lineage.append(base.key)
            inherited = base.document()
            # Children must declare identity, version and display name themselves.
            for key in ("id", "profile_version", "display_name", "extends"):
                inherited.pop(key, None)
            for key in ("regions", "locales"):
                if isinstance(doc.get(key), dict):
                    doc[key] = {**inherited.get(key, {}), **doc[key]}
            doc = {**inherited, **doc}
        try:
            normalized = normalize(load("profile", doc))
        except ContractError as exc:
            raise ProfileError(exc.issues) from exc
        # Older contracts remain readable; analysis requires these metadata fields.
        issues = []
        for name in ("license", "capabilities"):
            if name not in normalized:
                issues.append(f"{name}: required for analysis")
        seen: set[str] = set()
        for i, setting in enumerate(normalized["detectors"]):
            if setting["id"] in seen:
                issues.append(f"detectors[{i}].id: duplicate detector")
            seen.add(setting["id"])
            locale = setting.get("locale")
            if locale and locale not in normalized.get("locales", {}):
                issues.append(f"detectors[{i}].locale: no locale pack for {locale}")
        if issues:
            raise ProfileError(issues)
        return ResolvedProfile(canonical(normalized), digest([normalized, lineage]))


def compatibility(profile: dict[str, Any], width: int, height: int, locale: str | None) -> None:
    frame = profile["frame"]
    issues = []
    if width < frame["min_width"] or height < frame["min_height"]:
        issues.append("frame: source resolution is below the profile minimum")
    ratios = [tuple(map(int, r.split(":"))) for r in frame["aspect_ratios"]]
    if not any(abs(width / height - a / b) / (a / b) <= 0.01 for a, b in ratios):
        issues.append("frame.aspect_ratios: source aspect ratio is incompatible")
    if locale and locale not in profile.get("locales", {}):
        issues.append("locales: requested locale pack is unavailable")
    if issues:
        raise AnalysisError("profile.incompatible", "; ".join(issues))
