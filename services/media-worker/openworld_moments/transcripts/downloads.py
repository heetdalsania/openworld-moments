# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded, resumable explicit downloads; immutable verified versions and active pins."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path
from typing import Any

from openworld_moments.storage import utc_now
from openworld_moments.transcripts.catalog import Catalog, ModelEntry, read_catalog
from openworld_moments.transcripts.models import SpeechModels
from openworld_moments.transcripts.whisper import TranscriptionError, sha256_file

RESERVE = 64 * 1024**2
Progress = Callable[[int, int, str], None]


def checked_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not (host == "huggingface.co" or host.endswith((".huggingface.co", ".hf.co")))
    ):
        raise TranscriptionError(
            "models.origin_refused", "The model download origin is not allowed."
        )


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_download(url: str, offset: int) -> Any:
    checked_url(url)
    # A signed digest/revision binds resumed bytes even without an ETag.
    request = urllib.request.Request(  # noqa: S310 - HTTPS origins checked above
        url, headers={"Range": f"bytes={offset}-", "Accept-Encoding": "identity"}
    )
    opener = urllib.request.build_opener(Redirects())
    return opener.open(request, timeout=5)


def regular(path: Path) -> bool:
    try:
        info = path.lstat()
        return not path.is_symlink() and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    except OSError:
        return False


@cache
def operation_lock(root: str) -> threading.Lock:
    return threading.Lock()


class Downloads:
    def __init__(
        self,
        library: Path,
        *,
        catalog: Catalog | None = None,
        opener: Callable[[str, int], Any] = open_download,
    ) -> None:
        self.library = library
        self.models = SpeechModels(library)
        self.catalog = catalog
        self.opener = opener
        self.lock = operation_lock(str(library.resolve()))

    def manifest(self) -> Catalog:
        return self.catalog if self.catalog is not None else read_catalog()

    def entry(self, name: str) -> ModelEntry:
        for entry in self.manifest().models:
            if entry.name == name:
                return entry
        raise TranscriptionError("models.unknown", "Choose a model from the signed catalog.")

    def directory(self, leaf: str) -> Path:
        root = self.library
        for part in ("models", "whisper", leaf):
            root = root / part
            if root.is_symlink() or os.path.isjunction(root):
                raise TranscriptionError("models.unsafe_path", "Repair the linked model directory.")
            root.mkdir(exist_ok=True)
        return root

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        if not self.lock.acquire(blocking=False):
            raise TranscriptionError("models.busy", "A model operation is already running.")
        try:
            yield
        finally:
            self.lock.release()

    def status(self) -> dict[str, Any]:
        catalog = self.manifest()
        self.directory("versions")
        installed = {m.name: m for m in self.models.installed()}
        entries = []
        for model in catalog.models:
            partial = self.directory("downloads") / f"{model.name}-{model.sha256}.part"
            done = partial.stat().st_size if regular(partial) else 0
            if done > model.size_bytes:
                done = 0  # corrupt oversized partial cannot be resumed
            versions = self.directory("versions")
            saved = []
            for receipt in sorted(versions.glob(f"{model.name}-*.json")):
                try:
                    if not regular(receipt) or receipt.stat().st_size > 4096:
                        continue
                    doc = json.loads(receipt.read_text("utf-8"))
                    digest = doc["sha256"]
                    path = versions / f"{digest}.bin"
                    if (
                        not re.fullmatch(r"[a-f0-9]{64}", digest)
                        or not regular(receipt)
                        or not regular(path)
                        or sha256_file(path) != digest
                    ):
                        continue
                    saved.append(digest)
                except (ValueError, OSError, KeyError, TypeError):
                    continue
            entries.append(
                {
                    **model.model_dump(exclude={"url"}),
                    "downloaded_bytes": done,
                    "disk_required_bytes": max(0, model.size_bytes - done)
                    + model.size_bytes
                    + RESERVE,
                    "active_sha256": installed[model.name].sha256
                    if model.name in installed
                    else None,
                    "versions": saved,
                }
            )
        return {"schema_version": "1.23", "catalog_version": catalog.version, "models": entries}

    def activate(self, name: str, digest: str) -> None:
        self.entry(name)
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise TranscriptionError("models.invalid_pin", "Choose a verified installed version.")
        versions = self.directory("versions")
        receipt = versions / f"{name}-{digest}.json"
        path = versions / f"{digest}.bin"
        if not regular(receipt) or receipt.stat().st_size > 4096 or not regular(path):
            raise TranscriptionError(
                "models.version_missing", "That model version is not installed."
            )
        doc = json.loads(receipt.read_text("utf-8"))
        if doc.get("sha256") != digest or doc.get("name") != name or sha256_file(path) != digest:
            raise TranscriptionError(
                "models.corrupt", "That model failed verification; reinstall it."
            )
        self.models.install(path, name, str(doc["license"]), expected_sha256=digest)

    def change(self, name: str, digest: str | None) -> None:
        with self.exclusive():
            if digest is not None:
                self.activate(name, digest)
                return
            self.entry(name)
            # Remove only owned catalog versions, active model and partial bytes.
            versions = self.directory("versions")
            for receipt in versions.glob(f"{name}-*.json"):
                match = re.fullmatch(re.escape(name) + r"-([a-f0-9]{64})\.json", receipt.name)
                if match:
                    (versions / f"{match[1]}.bin").unlink(missing_ok=True)
                    receipt.unlink(missing_ok=True)
            (self.models.directory / f"ggml-{name}.bin").unlink(missing_ok=True)
            (self.models.directory / f"{name}.json").unlink(missing_ok=True)
            for partial in self.directory("downloads").glob(f"{name}-*.part"):
                if re.fullmatch(re.escape(name) + r"-[a-f0-9]{64}\.part", partial.name):
                    partial.unlink(missing_ok=True)

    def run(self, name: str, cancel: threading.Event, progress: Progress) -> dict[str, Any]:
        with self.exclusive():
            try:
                return self._run(self.entry(name), cancel, progress)
            except OSError as exc:
                code = "models.disk_full" if exc.errno == 28 else "models.write_failed"
                raise TranscriptionError(
                    code, "Check model-folder permissions and free space."
                ) from exc

    def _run(
        self, model: ModelEntry, cancel: threading.Event, progress: Progress
    ) -> dict[str, Any]:
        from openworld_moments.jobs.engine import Cancelled

        partial = self.directory("downloads") / f"{model.name}-{model.sha256}.part"
        if partial.is_symlink() or (partial.exists() and not regular(partial)):
            raise TranscriptionError("models.unsafe_path", "Remove the linked partial download.")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > model.size_bytes:
            partial.unlink()
            offset = 0
        needed = model.size_bytes - offset + model.size_bytes + RESERVE
        if shutil.disk_usage(self.library).free < needed:
            raise TranscriptionError(
                "models.disk_full", "Free more library space before installing."
            )
        try:
            if offset < model.size_bytes:
                if cancel.is_set():
                    raise Cancelled
                with self.opener(model.url, offset) as response:
                    status = response.status
                    if status == 200:
                        offset = 0  # server ignored Range; overwrite, never append a whole file
                    elif status != 206 or response.headers.get("Content-Range") != (
                        f"bytes {offset}-{model.size_bytes - 1}/{model.size_bytes}"
                    ):
                        raise TranscriptionError(
                            "models.bad_range", "Server returned an invalid range."
                        )
                    if response.headers.get("Content-Encoding", "identity") != "identity":
                        raise TranscriptionError(
                            "models.bad_range", "Unexpected transfer encoding."
                        )
                    with partial.open("ab" if offset else "wb") as stream:
                        while True:
                            if cancel.is_set():
                                raise Cancelled
                            chunk = response.read(min(256 * 1024, model.size_bytes - offset + 1))
                            if not chunk:
                                break
                            if offset + len(chunk) > model.size_bytes:
                                raise TranscriptionError(
                                    "models.too_large", "Model exceeds its signed size."
                                )
                            stream.write(chunk)
                            offset += len(chunk)
                            progress(offset, model.size_bytes, f"Downloading {model.name}")
            if cancel.is_set():
                raise Cancelled
            if offset != model.size_bytes:
                raise TranscriptionError(
                    "models.interrupted", "Download interrupted. Retry to resume."
                )
            if sha256_file(partial) != model.sha256:
                partial.unlink(missing_ok=True)
                raise TranscriptionError("models.corrupt", "Checksum mismatch. Download again.")
            if cancel.is_set():
                raise Cancelled
            versions = self.directory("versions")
            os.replace(partial, versions / f"{model.sha256}.bin")
            receipt = versions / f"{model.name}-{model.sha256}.json"
            fd, temp = tempfile.mkstemp(prefix=".receipt-", dir=versions)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({**model.model_dump(), "installed_at": utc_now()}, stream)
                os.replace(temp, receipt)
            finally:
                Path(temp).unlink(missing_ok=True)
            if cancel.is_set():
                raise Cancelled
            self.activate(model.name, model.sha256)
            return {"name": model.name, "sha256": model.sha256, "revision": model.revision}
        except TranscriptionError as exc:
            if exc.code == "models.too_large":
                partial.unlink(missing_ok=True)
            raise
        except (OSError, urllib.error.URLError) as exc:
            code = "models.disk_full" if getattr(exc, "errno", None) == 28 else "models.offline"
            raise TranscriptionError(
                code, "Download could not finish. Retry to resume safely."
            ) from exc
