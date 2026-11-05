# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run media tools (FFprobe, FFmpeg) safely.

* Commands are argument lists; nothing is passed through a shell.
* stdout is capped (the tool is killed past the cap) and stderr keeps only a
  redacted tail, so a hostile file cannot exhaust memory.
* A timeout or a set cancel event kills the process; it is always reaped
  before :func:`run_tool` returns or raises.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from openworld_moments.redaction import BoundedTail, Redactor

DEFAULT_MAX_STDOUT = 16 * 1024 * 1024
STDERR_TAIL_BYTES = 8192
_POLL_S = 0.05
_KILL_WAIT_S = 5.0


@dataclass(frozen=True)
class ToolResult:
    returncode: int
    stdout: bytes
    stderr_tail: str


class ToolError(Exception):
    """The tool could not run to completion. ``stderr_tail`` is already redacted."""

    def __init__(self, message: str, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail


class ToolNotStarted(ToolError):
    """The executable could not be started (missing, not executable, ...)."""


class ToolTimeout(ToolError):
    pass


class ToolCancelled(ToolError):
    pass


class ToolOutputTooLarge(ToolError):
    pass


def _popen_kwargs() -> dict[str, object]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}  # keep terminal signals away from the tool


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AV_LOG_FORCE_NOCOLOR"] = "1"
    return env


def run_tool(
    argv: Sequence[str],
    *,
    timeout_s: float,
    cancel: threading.Event | None = None,
    max_stdout: int = DEFAULT_MAX_STDOUT,
    redactor: Redactor | None = None,
    on_spawn: Callable[[subprocess.Popen[bytes]], None] | None = None,
) -> ToolResult:
    """Run ``argv`` to completion and return its exit code, stdout, and stderr tail.

    Raises :class:`ToolTimeout`, :class:`ToolCancelled`, :class:`ToolOutputTooLarge`,
    or :class:`ToolNotStarted`. A non-zero exit code is *not* an error here.
    """
    if not argv or any("\0" in a for a in argv):
        raise ToolNotStarted("invalid command")
    tail = BoundedTail(STDERR_TAIL_BYTES, redactor)
    try:
        proc = subprocess.Popen(  # noqa: S603 - argument list, no shell
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            env=_child_env(),
            **_popen_kwargs(),  # type: ignore[call-overload]
        )
    except OSError as exc:
        raise ToolNotStarted(
            f"could not start {os.path.basename(argv[0])}: {exc.strerror}"
        ) from exc
    if on_spawn is not None:
        on_spawn(proc)

    chunks: list[bytes] = []
    overflow = threading.Event()

    stdout, stderr = proc.stdout, proc.stderr
    if stdout is None or stderr is None:  # pragma: no cover - both are PIPE
        _kill(proc)
        raise ToolNotStarted("pipes unavailable")

    def read_stdout() -> None:
        size = 0
        while block := stdout.read(65536):
            size += len(block)
            if size > max_stdout:
                overflow.set()
                _kill(proc)
                break
            chunks.append(block)
        stdout.close()

    def read_stderr() -> None:
        while block := stderr.read(4096):
            tail.write(block.decode("utf-8", errors="replace"))
        stderr.close()

    readers = [
        threading.Thread(target=read_stdout, daemon=True, name="tool-stdout"),
        threading.Thread(target=read_stderr, daemon=True, name="tool-stderr"),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout_s
    outcome: type[ToolError] | None = None
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                outcome = ToolCancelled
                break
            if time.monotonic() >= deadline:
                outcome = ToolTimeout
                break
            if cancel is not None:
                cancel.wait(_POLL_S)
            else:
                time.sleep(_POLL_S)
    finally:
        if proc.poll() is None:
            _kill(proc)
        for reader in readers:
            reader.join(timeout=_KILL_WAIT_S)

    if outcome is ToolCancelled:
        raise ToolCancelled("cancelled", tail.text())
    if outcome is ToolTimeout:
        raise ToolTimeout(f"timed out after {timeout_s:g}s", tail.text())
    if overflow.is_set():
        raise ToolOutputTooLarge(f"output exceeded {max_stdout} bytes", tail.text())
    return ToolResult(proc.returncode, b"".join(chunks), tail.text())


def _kill(proc: subprocess.Popen[bytes]) -> None:
    """Kill and reap. FFprobe has no cleanup to do, so there is no polite phase."""
    with contextlib.suppress(OSError):  # already exited
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):  # pragma: no cover
        proc.wait(timeout=_KILL_WAIT_S)
