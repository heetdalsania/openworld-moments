# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicitly installed local speech models (spec 10.7). Nothing downloads, ever.

A model is a whisper.cpp ``ggml`` file the user obtained and installs from a local
path (``owm models install``). It is copied into ``<library>/models/whisper/`` with a
sidecar recording its name, size, SHA-256, declared license and install time. The
catalog lists well-known models with their source page so users can fetch one
themselves; listing it never contacts the network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openworld_moments.storage import utc_now
from openworld_moments.transcripts.whisper import TranscriptionError, sha256_file

MODELS_DIR = Path("models") / "whisper"
NAME = re.compile(r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$")
MAX_MODEL_BYTES = 4 * 1024 * 1024 * 1024
#: ggml model files start with the magic 0x67676d6c ("ggml") stored little-endian.
GGML_MAGICS = (b"lmgg", b"ggml", b"GGUF")
SOURCE = "https://huggingface.co/ggerganov/whisper.cpp"
SIZES_MB = {"tiny": 78, "base": 148, "small": 488, "medium": 1530}
CATALOG: tuple[dict[str, Any], ...] = tuple(
    {
        "name": f"{size}{suffix}",
        "approx_size_bytes": mb * 1_000_000,
        "languages": "en" if suffix else "multilingual",
        "license": "MIT",
        "source_url": SOURCE,
    }
    for size, mb in SIZES_MB.items()
    for suffix in (".en", "")
)


@dataclass(frozen=True)
class InstalledModel:
    name: str
    path: Path
    size_bytes: int
    sha256: str
    license: str
    installed_at: str

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "license": self.license,
            "installed_at": self.installed_at,
        }


class SpeechModels:
    def __init__(self, library_root: Path) -> None:
        self.directory = Path(library_root) / MODELS_DIR

    def _sidecar(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def _file(self, name: str) -> Path:
        return self.directory / f"ggml-{name}.bin"

    def installed(self) -> list[InstalledModel]:
        if not self.directory.is_dir():
            return []
        models = []
        for sidecar in sorted(self.directory.glob("*.json")):
            model = self._read(sidecar)
            if model is not None:
                models.append(model)
        return models

    def _read(self, sidecar: Path) -> InstalledModel | None:
        """A sidecar whose model file is missing or resized is ignored, not trusted."""
        try:
            if sidecar.stat().st_size > 16 * 1024:
                return None
            doc = json.loads(sidecar.read_text("utf-8"))
            name = doc["name"]
            if not isinstance(name, str) or not NAME.fullmatch(name) or len(name) > 64:
                return None
            path = self._file(name)
            if path.is_symlink() or not path.is_file() or path.stat().st_size != doc["size_bytes"]:
                return None
            return InstalledModel(
                name,
                path,
                int(doc["size_bytes"]),
                str(doc["sha256"]),
                str(doc["license"])[:100],
                str(doc["installed_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def get(self, name: str) -> InstalledModel:
        if NAME.fullmatch(name) and len(name) <= 64:
            model = self._read(self._sidecar(name))
            if model is not None:
                return model
        raise TranscriptionError(
            "transcription.model_missing",
            "That speech model is not installed. Install a model explicitly to transcribe.",
        )

    def install(self, source: Path, name: str, license_id: str) -> InstalledModel:
        """Copy a local ggml file in, after checking its name, size and magic bytes."""
        if not NAME.fullmatch(name) or len(name) > 64:
            raise TranscriptionError(
                "transcription.invalid_model", "Model names are lowercase letters, digits, . - _"
            )
        license_id = license_id.strip()
        if not license_id or len(license_id) > 100:
            raise TranscriptionError(
                "transcription.invalid_model", "Record the model's license when installing it."
            )
        source = Path(source)
        try:
            if source.is_symlink() or not source.is_file():
                raise ValueError("not a file")
            size = source.stat().st_size
            if not 1024 <= size <= MAX_MODEL_BYTES:
                raise ValueError("size")
            with source.open("rb") as stream:
                if stream.read(4) not in GGML_MAGICS:
                    raise ValueError("magic")
        except (OSError, ValueError) as exc:
            raise TranscriptionError(
                "transcription.invalid_model", "That file is not a whisper.cpp ggml model."
            ) from exc
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".install-", dir=self.directory)
        os.close(fd)
        try:
            shutil.copyfile(source, temp)
            digest = sha256_file(Path(temp))
            os.replace(temp, self._file(name))
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        doc = {
            "name": name,
            "size_bytes": size,
            "sha256": digest,
            "license": license_id,
            "installed_at": utc_now(),
        }
        self._sidecar(name).write_text(json.dumps(doc, indent=2) + "\n", "utf-8")
        return self.get(name)

    def remove(self, name: str) -> None:
        model = self.get(name)
        model.path.unlink(missing_ok=True)
        self._sidecar(name).unlink(missing_ok=True)
