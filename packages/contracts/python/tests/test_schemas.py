# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import re

from conftest import FIXTURES, SCHEMAS
from jsonschema import Draft202012Validator

from openworld_moments_contracts import CONTRACTS
from openworld_moments_contracts.validate import _schema_text

ID_BASE = "https://github.com/heetdalsania/openworld-moments/contracts/"

# Contracts must stay game-neutral: no publisher, title, place, or character names.
BANNED_TERMS = [
    "gta",
    "grand theft",
    "rockstar",
    "take-two",
    "los santos",
    "vice city",
    "leonida",
    "liberty city",
    "lucia",
    "jason",
]
BANNED = re.compile(r"\b(" + "|".join(map(re.escape, BANNED_TERMS)) + r")\b", re.IGNORECASE)


def test_every_schema_is_valid_2020_12_with_matching_id() -> None:
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = json.loads(path.read_text("utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == ID_BASE + path.name


def test_top_level_objects_are_closed() -> None:
    for contract in CONTRACTS:
        schema = json.loads((SCHEMAS / f"{contract}.schema.json").read_text("utf-8"))
        if "oneOf" in schema:  # a union of records (event JSONL lines): every branch closed
            for branch in schema["oneOf"]:
                name = branch["$ref"].removeprefix("#/$defs/")
                assert schema["$defs"][name]["additionalProperties"] is False, (contract, name)
        else:
            assert schema["additionalProperties"] is False, contract


def test_vendored_schemas_match_sources() -> None:
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        assert _schema_text(path.name.removesuffix(".schema.json")) == path.read_text("utf-8")


def test_no_game_specific_names_in_schemas_or_fixtures() -> None:
    for path in [*SCHEMAS.glob("*.json"), *FIXTURES.rglob("*.json")]:
        hit = BANNED.search(path.read_text("utf-8"))
        assert hit is None, f"{path.name} contains {hit.group(0)!r}"
