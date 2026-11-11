# SPDX-License-Identifier: AGPL-3.0-or-later
"""Malformed media, hostile names and resource limits (M30 fuzz corpus).

Every corpus file is probed, imported and uploaded through the phone gateway. Each
must end in a contract-valid result or a stable error code, within a bounded time,
without leaking its path, writing outside the library or staging, or changing the
source file.
"""

from __future__ import annotations

import hashlib
import re
import time
from contextlib import closing
from pathlib import Path

import pytest
from openworld_moments_contracts.generated.media_asset_schema import MediaProbe
from starlette.testclient import TestClient

from openworld_moments.exports.formats import safe_filename
from openworld_moments.gateway.app import Session, create_app
from openworld_moments.gateway.uploads import Limits, sanitize_name
from openworld_moments.media.probe import ProbeError, probe_file
from openworld_moments.media.tools import ToolInfo
from tests.media.test_import import Harness
from tests.security.corpus import HOSTILE_NAMES, mutants, structural, truncations, write

CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
#: Bound per probe; FFprobe's own timeout is longer, so this catches hangs early.
PROBE_BUDGET_S = 20.0
RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(10)),
    *(f"lpt{i}" for i in range(10)),
}


@pytest.fixture(scope="module")
def corpus(media_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    valid = (media_dir / "h264_aac.mp4").read_bytes()
    files = {**structural(), **truncations(valid), **mutants(valid)}
    return write(tmp_path_factory.mktemp("corpus"), files)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_probe_handles_every_malformed_file(corpus: list[Path], ffprobe: ToolInfo) -> None:
    outcomes: dict[str, int] = {}
    for path in corpus:
        before = digest(path)
        started = time.monotonic()
        try:
            probe = probe_file(path, ffprobe)
        except ProbeError as error:
            assert CODE.match(error.code), (path.name, error.code)
            assert str(path) not in error.message and str(path) not in error.stderr_tail
            outcomes[error.code] = outcomes.get(error.code, 0) + 1
        else:
            MediaProbe.model_validate(probe)  # whatever succeeds is contract-valid
            outcomes["probed"] = outcomes.get("probed", 0) + 1
        assert time.monotonic() - started < PROBE_BUDGET_S, path.name
        assert digest(path) == before, f"{path.name} was modified"
    # The structural cases are never accepted as media.
    for name in ("empty.mp4", "one-byte.mp4", "text.mov", "png-header.mov", "zip-header.mkv"):
        with pytest.raises(ProbeError):
            probe_file(next(p for p in corpus if p.name == name), ffprobe)
    assert sum(outcomes.values()) == len(corpus)


def test_import_never_writes_outside_the_library(
    corpus: list[Path], tmp_path: Path, ffprobe: ToolInfo
) -> None:
    sources = {p: digest(p) for p in corpus}
    with closing(Harness(tmp_path, ffprobe)) as harness:
        try:
            result = harness.run(*corpus, mode="managed", recursive=False)
            items = result["items"]
        except Exception as failure:  # nothing importable: ImportFailure carries the result
            items = failure.result["items"]  # type: ignore[attr-defined]
        assert len(items) == len(corpus)
        assert {item["outcome"] for item in items} <= {"imported", "existing", "failed", "skipped"}
        for item in items:
            if item["outcome"] == "failed":
                assert CODE.match(item["error"]["code"]), item
                assert str(tmp_path) not in item["error"]["message"]
        imported = sum(1 for item in items if item["outcome"] == "imported")
        assert harness.asset_count() == imported
        library = harness.library.root
        managed = [p for p in (library / "managed-media").rglob("*") if p.is_file()]
        assert len(managed) == imported
        staging = library / "staging"
        assert not staging.exists() or not any(p.is_file() for p in staging.rglob("*"))
    assert {p: digest(p) for p in corpus} == sources


def test_gateway_uploads_stay_in_staging(corpus: list[Path], tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    session = Session(
        token="e" * 64,
        staging=staging,
        expires_at=time.monotonic() + 600,
        limits=Limits(max_files=len(corpus), free_space_margin=0, max_attempts=len(corpus) + 1),
    )
    client = TestClient(create_app(session))
    statuses = []
    for path in corpus:
        response = client.put(
            f"/u/{'e' * 64}/files", params={"name": path.name}, content=path.read_bytes()
        )
        statuses.append(response.status_code)
        assert response.status_code == 200 or response.json()["status"] == "rejected"
    stored = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert all(p.resolve().is_relative_to(staging.resolve()) for p in stored)
    # Disguised or empty uploads are refused and leave nothing behind.
    assert statuses.count(200) == len(stored)
    assert len(stored) < len(corpus)


@pytest.mark.parametrize("raw", HOSTILE_NAMES)
def test_hostile_names_become_one_safe_component(raw: str) -> None:
    for name in (sanitize_name(raw, 7), safe_filename(raw, "otio")):
        assert name and name not in (".", "..")
        assert not re.search(r"[\\/\x00-\x1f‮]", name), repr(name)
        assert len(name.encode("utf-8")) <= 255
        assert name.split(".")[0].lower() not in RESERVED, name
