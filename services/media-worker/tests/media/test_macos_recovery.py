# SPDX-License-Identifier: AGPL-3.0-or-later
"""M35 metadata and cache fixtures; these do not simulate OS consent or a provider."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openworld_moments.derived.layout import DerivedPaths
from openworld_moments.ingest.files import FileStepError, snapshot
from openworld_moments.ingest.scan import Problem, scan
from openworld_moments.media.availability import SF_DATALESS, cloud_only
from openworld_moments.media.probe import ProbeError, precheck


def test_cloud_metadata_is_refused_before_any_open(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "Cloud ✓.mp4"
    path.write_bytes(b"original bytes")
    original_stat = Path.stat
    original_open = Path.open
    info = path.stat()
    cloud = SimpleNamespace(
        st_flags=SF_DATALESS,
        st_mode=info.st_mode,
        st_size=info.st_size,
        st_ino=info.st_ino,
        st_dev=info.st_dev,
        st_mtime_ns=info.st_mtime_ns,
    )

    def stat(p: Path, **kwargs: Any) -> Any:
        return cloud if p == path else original_stat(p, **kwargs)

    def open_file(p: Path, *args: Any, **kwargs: Any) -> Any:
        if p == path:
            raise AssertionError("placeholder must not be opened")
        return original_open(p, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(ProbeError) as probe:
        precheck(path)
    assert probe.value.code == "media.download_required" and probe.value.retryable
    with pytest.raises(FileStepError) as step:
        snapshot(path)
    assert step.value.code == "media.download_required"
    (problem,) = scan([str(path)], recursive=True)
    assert isinstance(problem, Problem)
    assert problem.code == "media.download_required" and problem.retryable
    # Hydration completed: identical bytes can be selected again, without a reset.
    monkeypatch.setattr(Path, "stat", original_stat)
    monkeypatch.setattr(Path, "open", original_open)
    assert precheck(path) == len(b"original bytes")
    assert path.read_bytes() == b"original bytes"


def test_hidden_or_sparse_local_files_are_not_cloud_placeholders() -> None:
    assert not cloud_only(SimpleNamespace(st_flags=0x8000, st_blocks=0))  # type: ignore[arg-type]
    for flags in (0x1000, 0x40000, 0x400000):
        assert cloud_only(SimpleNamespace(st_file_attributes=flags))  # type: ignore[arg-type]


def test_cache_root_does_not_move_canonical_media_or_models(tmp_path: Path) -> None:
    library, cache = tmp_path / "Application Support ✓", tmp_path / "Caches ✓"
    paths = DerivedPaths(library, cache)
    rel = paths.relpath("ast_01JCBQ00000000000000000001", "proxy", "ab" * 32)
    target = paths.resolve(rel)
    assert target == cache / rel
    assert paths.root == library
    assert paths.staging.is_relative_to(cache)
    legacy = library / rel
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy playback copy")
    assert target is not None and not target.exists()  # normal cache miss, regenerated on demand
    assert paths.resolve("../managed-media/source.mp4") is None
    staging = paths.job_staging("job_fixture")
    staging.mkdir(parents=True)
    (staging / "partial.mp4").write_bytes(b"partial")
    paths.clean_staging()
    assert not staging.exists()
    assert legacy.read_bytes() == b"legacy playback copy"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions fixture")
def test_permission_loss_and_return_preserve_source(tmp_path: Path) -> None:
    path = tmp_path / "Permission ✓.mp4"
    path.write_bytes(b"original bytes")
    path.chmod(0)
    try:
        with pytest.raises(ProbeError) as error:
            precheck(path)
        assert error.value.code == "media.permission_denied"
    finally:
        path.chmod(0o600)
    assert precheck(path) == len(b"original bytes")
    assert path.read_bytes() == b"original bytes"
