# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session transcription (M18): optional, local, per-clip restartable, deletable.

For each session clip the checked M08 proxy's first audio stream is extracted to an
owned 16 kHz mono WAV, transcribed by the user's whisper.cpp with an explicitly
installed model, mapped into M13 unique session time, and committed in its own
transaction. Cancelling kills FFmpeg or the engine and removes the scratch folder;
completed clips stay cached. Deleting a transcript removes only derived text.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from openworld_moments_contracts import load, normalize

from openworld_moments.derived.service import DerivedCancelled, DerivedMedia
from openworld_moments.detectors.profiles import canonical, digest
from openworld_moments.detectors.sdk import AnalysisCancelled, AnalysisError
from openworld_moments.detectors.service import Analyzer
from openworld_moments.media.process import ToolCancelled, ToolError, run_tool
from openworld_moments.media.tools import MediaTools
from openworld_moments.redaction import Redactor
from openworld_moments.storage import (
    AssetRepository,
    Database,
    SessionRepository,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import SCHEMA_VERSION
from openworld_moments.transcripts.models import CATALOG, SpeechModels
from openworld_moments.transcripts.whisper import (
    Engine,
    Recognition,
    TranscriptionCancelled,
    TranscriptionError,
    locate,
    probe_engine,
    sha256_file,
    transcribe_wav,
)

TRANSCRIBER_VERSION = "1.0.0"
WAV_RATE = 16000
STAGING = Path("staging") / "transcripts"
Progress = Callable[[int, int, str], None]
EngineFactory = Callable[[threading.Event | None], Engine]


def default_engine(cancel: threading.Event | None = None) -> Engine:
    path = locate()
    if path is None:
        raise TranscriptionError(
            "transcription.engine_missing",
            "Install whisper.cpp (whisper-cli) to enable optional local transcription.",
        )
    return probe_engine(path, cancel)


def map_to_session(
    recognition: Recognition, hidden_ms: int, virtual_start_ms: int
) -> list[dict[str, Any]]:
    """Source-clip segments → unique session time. Words entirely inside the hidden
    repeated start of a clip are dropped (that speech already plays in the previous
    clip); a word crossing the boundary starts at the first unique moment."""

    def virtual(ms: int) -> int:
        return virtual_start_ms + max(hidden_ms, ms) - hidden_ms

    segments = []
    for seg in recognition.segments:
        if seg.end_ms <= hidden_ms:
            continue  # entirely inside the repeated footage
        words = [w for w in seg.words if w.end_ms > hidden_ms]
        if seg.words and not words:
            continue
        text = seg.text if len(words) == len(seg.words) else " ".join(w.text for w in words)
        source_start = max(seg.start_ms, hidden_ms)
        source_end = max(source_start, seg.end_ms)
        confidence = (
            round(sum(w.confidence for w in words) / len(words), 4) if words else seg.confidence
        )
        segments.append(
            {
                "start_ms": virtual(source_start),
                "end_ms": virtual(source_end),
                "source_start_ms": source_start,
                "source_end_ms": source_end,
                "text": text[:2000],
                "confidence": confidence,
                "words": [
                    {
                        "text": w.text,
                        "start_ms": virtual(max(w.start_ms, hidden_ms)),
                        "end_ms": virtual(max(w.end_ms, hidden_ms)),
                        "source_start_ms": max(w.start_ms, hidden_ms),
                        "source_end_ms": max(w.end_ms, hidden_ms),
                        "confidence": w.confidence,
                    }
                    for w in words
                ],
            }
        )
    return segments


class Transcriber:
    def __init__(
        self,
        database: Database,
        tools: MediaTools,
        derived: DerivedMedia,
        *,
        engine: EngineFactory = default_engine,
        threads: int | None = None,
    ) -> None:
        self.database, self.tools, self.derived = database, tools, derived
        self.analyzer = Analyzer(database, tools, derived)
        self.root = derived.paths.root
        self.staging = (derived.paths.cache_root or self.root) / STAGING
        self.models = SpeechModels(self.root)
        self.engine_factory = engine
        self.threads = threads or max(1, min(4, os.cpu_count() or 1))

    # -- status ----------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Engine availability, installed models and the manual-install catalog."""
        engine: dict[str, Any]
        try:
            found = self.engine_factory(None)
            engine = {"available": True, "version": found.version}
        except TranscriptionError as exc:
            engine = {"available": False, "reason": exc.message}
        return normalize(
            load(
                "speech-models",
                {
                    "schema_version": SCHEMA_VERSION,
                    "engine": engine,
                    "installed": [m.public() for m in self.models.installed()],
                    "catalog": list(CATALOG),
                },
            )
        )

    def check_request(self, model: str) -> None:
        """Refuse a request up front when the engine or model is missing."""
        self.models.get(model)
        self.engine_factory(None)

    def clean_staging(self) -> None:
        """Remove scratch WAVs left by a crash. Only when no transcription runs."""
        target = self.staging
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)

    # -- transcripts -----------------------------------------------------------------

    def transcript(self, sid: str) -> dict[str, Any]:
        with contextlib.closing(self.database.connect()) as conn:
            SessionRepository(conn).get(sid)
            rows = conn.execute(
                "SELECT id, asset_id, start_ms, end_ms, source_start_ms, source_end_ms, text, "
                "language, confidence, words_json, transcriber_json FROM transcript_segments "
                "WHERE session_id=? AND transcriber_json IS NOT NULL ORDER BY start_ms, id",
                (sid,),
            ).fetchall()
        segments = [
            {
                "id": r[0],
                "asset_id": r[1],
                "start_ms": r[2],
                "end_ms": r[3],
                "source_start_ms": r[4],
                "source_end_ms": r[5],
                "text": r[6],
                "language": r[7],
                "confidence": r[8],
                "words": json.loads(r[9] or "[]"),
                "transcriber": json.loads(r[10]),
            }
            for r in rows
        ]
        return normalize(
            load(
                "transcript",
                {"schema_version": SCHEMA_VERSION, "session_id": sid, "segments": segments},
            )
        )

    def delete(self, sid: str) -> dict[str, int]:
        """Delete the session's derived transcript text. Media is never touched."""
        with contextlib.closing(self.database.connect()) as conn:
            SessionRepository(conn).get(sid)
            with transaction(conn):
                deleted = conn.execute(
                    "DELETE FROM transcript_segments WHERE session_id=?", (sid,)
                ).rowcount
                conn.execute("DELETE FROM transcript_runs WHERE session_id=?", (sid,))
        return {"deleted_segments": deleted}

    # -- the job ---------------------------------------------------------------------

    def run(
        self,
        params: Mapping[str, Any],
        *,
        job_id: str,
        cancel: threading.Event | None = None,
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        cancel = cancel or threading.Event()
        report = progress or (lambda *_: None)
        sid: str = params["session_id"]
        language: str = params.get("language", "auto")
        model = self.models.get(params["model"])
        engine = self.engine_factory(cancel)

        def check() -> None:
            if cancel.is_set():
                raise TranscriptionCancelled

        model_sha = sha256_file(model.path, check)
        if model_sha != model.sha256:
            raise TranscriptionError(
                "transcription.model_changed",
                "The installed model file changed; install it again before transcribing.",
            )
        transcriber = {
            "engine": "whisper.cpp",
            "engine_version": engine.version,
            "engine_sha256": engine.sha256,
            "model": model.name,
            "model_sha256": model_sha,
            "transcriber_version": TRANSCRIBER_VERSION,
            "requested_language": language,
        }
        outcomes: list[dict[str, Any]] = []
        with contextlib.closing(self.database.connect()) as conn:
            SessionRepository(conn).get(sid)
            links = SessionRepository(conn).assets(sid)
            layout = Analyzer.layout(conn, sid)
            total = max(1, len(links))
            report(0, total * 100, "Preparing transcription")
            virtual_start = 0
            for index, link in enumerate(links):
                check()
                hidden = (link.overlap_with_previous_ms or 0) if index else 0
                asset = AssetRepository(conn).get(link.asset_id)
                outcome: dict[str, Any] = {
                    "asset_id": link.asset_id,
                    "status": "computed",
                    "segment_count": 0,
                }
                try:
                    if not asset.audio:
                        raise TranscriptionError(
                            "transcription.no_audio", "This clip has no audio."
                        )
                    path, input_key = self.analyzer.checked_proxy(
                        conn, link.asset_id, job_id, cancel
                    )
                    key = digest(
                        [
                            TRANSCRIBER_VERSION,
                            transcriber,
                            input_key,
                            layout,
                            link.asset_id,
                            "audio:first-stream",
                        ]
                    )
                    cached = conn.execute(
                        "SELECT segment_count, language FROM transcript_runs "
                        "WHERE session_id=? AND asset_id=? AND cache_key=?",
                        (sid, link.asset_id, key),
                    ).fetchone()
                    if cached is not None and not params.get("force", False):
                        outcome.update(status="cached", segment_count=cached[0])
                        if cached[1]:
                            outcome["language"] = cached[1]
                    else:
                        recognition = self._recognize(
                            engine, model.path, path, language, asset.duration_ms, job_id, cancel
                        )
                        rows = map_to_session(recognition, hidden, virtual_start)
                        check()
                        if sha256_file(model.path, check) != model_sha:
                            raise TranscriptionError(
                                "transcription.model_changed",
                                "The installed model file changed during transcription.",
                            )
                        with transaction(conn):
                            if Analyzer.layout(conn, sid) != layout:
                                raise TranscriptionError(
                                    "transcription.session_changed",
                                    "The session changed during transcription; run it again.",
                                )
                            self._save(
                                conn, sid, link.asset_id, key, recognition, rows, transcriber
                            )
                        outcome["segment_count"] = len(rows)
                        if recognition.language:
                            outcome["language"] = recognition.language
                except (
                    TranscriptionCancelled,
                    ToolCancelled,
                    AnalysisCancelled,
                    DerivedCancelled,
                ) as exc:
                    raise TranscriptionCancelled from exc
                except (TranscriptionError, AnalysisError) as exc:
                    outcome.update(
                        status="skipped" if exc.code == "transcription.no_audio" else "failed",
                        segment_count=0,
                        error={"code": exc.code, "message": exc.message, "retryable": True},
                    )
                    outcome.pop("language", None)
                except Exception:
                    # Never surface exception text: it may contain transcript fragments.
                    outcome.update(
                        status="failed",
                        segment_count=0,
                        error={
                            "code": "transcription.failed",
                            "message": "Transcription failed for this clip; others are kept.",
                            "retryable": True,
                        },
                    )
                    outcome.pop("language", None)
                outcomes.append(outcome)
                report((index + 1) * 100, total * 100, "Clip transcribed")
                virtual_start += max(0, asset.duration_ms - hidden)
        return normalize(
            load(
                "transcription",
                {
                    "schema_version": SCHEMA_VERSION,
                    "session_id": sid,
                    "model": model.name,
                    "outcomes": outcomes,
                },
            )
        )

    def _recognize(
        self,
        engine: Engine,
        model: Path,
        proxy: Path,
        language: str,
        duration_ms: int,
        job_id: str,
        cancel: threading.Event,
    ) -> Recognition:
        staging = self.staging
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{job_id}-", dir=staging) as tmp:
            wav = Path(tmp) / "clip.wav"
            try:
                result = run_tool(
                    [
                        *self.tools.tool("ffmpeg").command,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-protocol_whitelist",
                        "file",
                        "-i",
                        f"file:{proxy}",
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        str(WAV_RATE),
                        "-c:a",
                        "pcm_s16le",
                        "-f",
                        "wav",
                        f"file:{wav}",
                    ],
                    timeout_s=600,
                    cancel=cancel,
                    redactor=Redactor([tmp, str(proxy.parent)]),
                )
            except ToolCancelled as exc:
                raise TranscriptionCancelled from exc
            except ToolError as exc:
                raise TranscriptionError(
                    "transcription.audio_failed", "The clip's audio could not be prepared."
                ) from exc
            if result.returncode or not wav.is_file():
                raise TranscriptionError(
                    "transcription.audio_failed", "The clip's audio could not be prepared."
                )
            return transcribe_wav(
                engine,
                model,
                wav,
                language=language,
                duration_ms=duration_ms,
                threads=self.threads,
                cancel=cancel,
            )

    @staticmethod
    def _save(
        conn: sqlite3.Connection,
        sid: str,
        aid: str,
        key: str,
        recognition: Recognition,
        rows: list[dict[str, Any]],
        transcriber: dict[str, Any],
    ) -> None:
        conn.execute(
            "DELETE FROM transcript_segments WHERE session_id=? AND asset_id=?", (sid, aid)
        )
        now = utc_now()
        provenance = canonical(transcriber)
        for row in rows:
            conn.execute(
                "INSERT INTO transcript_segments (session_id, start_ms, end_ms, speaker, text, "
                "language, confidence, words_json, asset_id, source_start_ms, source_end_ms, "
                "transcriber_json, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    row["start_ms"],
                    row["end_ms"],
                    row["text"],
                    recognition.language,
                    row["confidence"],
                    canonical(row["words"]),
                    aid,
                    row["source_start_ms"],
                    row["source_end_ms"],
                    provenance,
                    now,
                ),
            )
        conn.execute(
            "INSERT INTO transcript_runs VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, asset_id) DO UPDATE SET cache_key=excluded.cache_key, "
            "language=excluded.language, segment_count=excluded.segment_count, "
            "computed_at=excluded.computed_at",
            (sid, aid, key, recognition.language, len(rows), now),
        )
