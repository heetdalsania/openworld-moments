# SPDX-License-Identifier: Apache-2.0
"""Single entry point for reading contract documents: version → schema → semantics → model."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from openworld_moments_contracts.errors import ContractError
from openworld_moments_contracts.generated import (
    error_schema,
    event_schema,
    export_manifest_schema,
    job_schema,
    media_asset_schema,
    profile_schema,
    project_schema,
    render_preset_schema,
)
from openworld_moments_contracts.semantic import semantic_issues
from openworld_moments_contracts.versioning import check_version

#: Top-level contracts: name -> (model, carries schema_version).
CONTRACTS: dict[str, tuple[type[BaseModel], bool]] = {
    "error": (error_schema.ErrorInfo, False),
    "event": (event_schema.Event, True),
    "export-manifest": (export_manifest_schema.ExportManifest, True),
    "job": (job_schema.Job, True),
    "media-asset": (media_asset_schema.MediaAsset, True),
    "profile": (profile_schema.Profile, True),
    "project": (project_schema.Project, True),
    "render-preset": (render_preset_schema.RenderPreset, True),
}


def _schema_text(name: str) -> str:
    return (resources.files(__package__) / "schemas" / f"{name}.schema.json").read_text("utf-8")


@cache
def _registry() -> Registry[Any]:
    folder = resources.files(__package__) / "schemas"
    pairs = []
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".schema.json"):
            schema = json.loads(entry.read_text("utf-8"))
            pairs.append((schema["$id"], Resource.from_contents(schema, DRAFT202012)))
    return Registry().with_resources(pairs)


@cache
def _validator(contract: str) -> Draft202012Validator:
    schema = json.loads(_schema_text(contract))
    return Draft202012Validator(schema, registry=_registry())


def _path(parts: Any) -> str:
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(root)"


def load(contract: str, document: Any) -> BaseModel:
    """Validate ``document`` against ``contract`` and return the parsed model.

    Raises ContractVersionError for version problems and ContractError otherwise.
    """
    if contract not in CONTRACTS:
        raise KeyError(f"unknown contract {contract!r}; expected one of {sorted(CONTRACTS)}")
    model, versioned = CONTRACTS[contract]
    if versioned:
        check_version(contract, document)

    errors = sorted(_validator(contract).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        raise ContractError(contract, [f"{_path(e.path)}: {e.message}" for e in errors])

    issues = semantic_issues(contract, document)
    if issues:
        raise ContractError(contract, issues)

    try:
        return model.model_validate(document)
    except ValidationError as exc:  # schema and model disagree: a generator bug
        raise ContractError(contract, [f"model rejected a schema-valid document: {exc}"]) from exc


def normalize(model: BaseModel) -> dict[str, Any]:
    """Canonical JSON-compatible value. Equal to the TypeScript normalize() for the same input."""
    dumped = model.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return _canonical(dumped)  # type: ignore[no-any-return]


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
