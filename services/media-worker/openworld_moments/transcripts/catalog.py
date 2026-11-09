# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bundled, offline Ed25519 model manifest. Only explicit installs use the network."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from openworld_moments.transcripts.whisper import TranscriptionError

DATA = Path(__file__).parent / "catalog"
# Trust root is pinned in the application, never read from a downloaded manifest.
PUBLIC_KEY = "ccd039b62492513b5e0b951637bf81bd500f8d4112ca37153a32282a09ea3feb"


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$", max_length=64)
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    size_bytes: int = Field(ge=1024, le=4 * 1024**3)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license: str = Field(pattern="^MIT$")
    source_url: str = Field(max_length=300)
    url: str = Field(max_length=300)


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1)
    models: list[ModelEntry] = Field(min_length=1, max_length=64)


def read_catalog(
    data: bytes | None = None, signature: bytes | None = None, *, public_key: str = PUBLIC_KEY
) -> Catalog:
    """Verify exact bytes before parsing or interpreting URLs. No online refresh."""
    try:
        if data is None:
            with (DATA / "models.json").open("rb") as stream:
                data = stream.read(64 * 1024 + 1)
        if signature is None:
            with (DATA / "models.sig").open("rb") as stream:
                signature = stream.read(129)
        raw, sig = data, signature
        if len(raw) > 64 * 1024 or len(sig) > 128:
            raise ValueError("size")
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            base64.b64decode(sig, validate=True), raw
        )
        catalog = Catalog.model_validate(json.loads(raw))
        names = [m.name for m in catalog.models]
        if len(names) != len(set(names)):
            raise ValueError("duplicates")
        for model in catalog.models:
            expected = (
                "https://huggingface.co/ggerganov/whisper.cpp/resolve/"
                f"{model.revision}/ggml-{model.name}.bin"
            )
            if model.url != expected or not re.fullmatch(
                r"https://huggingface.co/ggerganov/whisper.cpp", model.source_url
            ):
                raise ValueError("origin")
        return catalog
    except (OSError, ValueError, InvalidSignature) as exc:
        raise TranscriptionError(
            "models.catalog_invalid", "The signed model catalog is invalid. Repair the application."
        ) from exc
