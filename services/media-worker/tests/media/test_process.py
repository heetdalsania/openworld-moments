# SPDX-License-Identifier: AGPL-3.0-or-later
"""Timeouts, cancellation, output bounds, and cleanup for media tool processes."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from openworld_moments.media.process import (
    STDERR_TAIL_BYTES,
    ToolCancelled,
    ToolNotStarted,
    ToolOutputTooLarge,
    ToolTimeout,
    run_tool,
)
from openworld_moments.redaction import Redactor

PY = sys.executable
SLEEP = "import time; time.sleep(60)"


def _capture() -> tuple[list[subprocess.Popen[bytes]], object]:
    spawned: list[subprocess.Popen[bytes]] = []
    return spawned, spawned.append


def test_success_returns_output_and_exit_code() -> None:
    result = run_tool(
        [PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
        timeout_s=30,
    )
    assert result.returncode == 3
    assert result.stdout.strip() == b"out"
    assert "err" in result.stderr_tail


def test_timeout_kills_and_reaps() -> None:
    spawned, hook = _capture()
    started = time.monotonic()
    with pytest.raises(ToolTimeout):
        run_tool([PY, "-c", SLEEP], timeout_s=0.5, on_spawn=hook)  # type: ignore[arg-type]
    assert time.monotonic() - started < 10
    assert spawned[0].poll() is not None, "the process must be dead and reaped"


def test_cancel_kills_promptly() -> None:
    spawned, hook = _capture()
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(ToolCancelled):
        run_tool([PY, "-c", SLEEP], timeout_s=60, cancel=cancel, on_spawn=hook)  # type: ignore[arg-type]
    assert time.monotonic() - started < 5
    assert spawned[0].poll() is not None


def test_already_cancelled_never_waits() -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ToolCancelled):
        run_tool([PY, "-c", SLEEP], timeout_s=60, cancel=cancel)


def test_stdout_is_capped() -> None:
    spawned, hook = _capture()
    flood = "import sys\nwhile True: sys.stdout.write('x' * 65536)"
    with pytest.raises(ToolOutputTooLarge):
        run_tool([PY, "-c", flood], timeout_s=30, max_stdout=200_000, on_spawn=hook)  # type: ignore[arg-type]
    assert spawned[0].poll() is not None


def test_stderr_keeps_a_bounded_redacted_tail(tmp_path: Path) -> None:
    secret_path = str(tmp_path / "Private Clip.mp4")
    script = (
        "import sys\n"
        "for i in range(5000): print('noise', i, file=sys.stderr)\n"
        f"print('failed on', {secret_path!r}, file=sys.stderr)\n"
    )
    result = run_tool([PY, "-c", script], timeout_s=30, redactor=Redactor([secret_path]))
    assert len(result.stderr_tail) <= STDERR_TAIL_BYTES
    assert "failed on" in result.stderr_tail
    assert secret_path not in result.stderr_tail
    assert "noise 0\n" not in result.stderr_tail


def test_missing_executable_is_not_started(tmp_path: Path) -> None:
    with pytest.raises(ToolNotStarted):
        run_tool([str(tmp_path / "no-such-tool")], timeout_s=5)


def test_nul_in_arguments_is_refused() -> None:
    with pytest.raises(ToolNotStarted):
        run_tool([PY, "-c", "pass", "bad\0arg"], timeout_s=5)


def test_shell_metacharacters_are_plain_arguments(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    nasty = f"; touch {marker} && echo $(id) | cat `whoami`"
    result = run_tool([PY, "-c", "import sys; print(sys.argv[1])", nasty], timeout_s=30)
    assert result.stdout.decode().strip() == nasty
    assert not marker.exists()


def test_streamed_stdout_is_not_collected_or_capped(tmp_path: Path) -> None:
    received: list[bytes] = []
    script = "import sys; sys.stdout.buffer.write(b'x' * 300000); sys.stdout.flush()"
    result = run_tool([PY, "-c", script], timeout_s=30, max_stdout=10, on_stdout=received.append)
    assert result.returncode == 0 and result.stdout == b""
    assert sum(len(b) for b in received) == 300000  # max_stdout does not apply when streaming


def test_cwd_lets_arguments_name_local_files(tmp_path: Path) -> None:
    run_tool([PY, "-c", "open('made.txt', 'w').write('ok')"], timeout_s=30, cwd=tmp_path)
    assert (tmp_path / "made.txt").read_text() == "ok"


def test_failing_stdout_callback_kills_the_tool() -> None:
    spawned, hook = _capture()

    def explode(_: bytes) -> None:
        raise RuntimeError("bad data")

    script = "import sys, time\nwhile True:\n    print('tick', flush=True)\n    time.sleep(0.01)"
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="bad data"):
        run_tool([PY, "-c", script], timeout_s=30, on_stdout=explode, on_spawn=hook)  # type: ignore[arg-type]
    assert time.monotonic() - started < 10
    assert spawned[0].poll() is not None


def test_cancel_while_streaming() -> None:
    cancel = threading.Event()

    def stop(_: bytes) -> None:
        cancel.set()

    script = "import time\nwhile True:\n    print('tick', flush=True)\n    time.sleep(0.01)"
    with pytest.raises(ToolCancelled):
        run_tool([PY, "-c", script], timeout_s=30, cancel=cancel, on_stdout=stop)


SHIM = """
import subprocess, sys, time
# Like a package-manager shim: start the real tool as a child and wait for it.
child = subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
child.wait()
"""
TOOL = """
import sys, time
with open(sys.argv[1], "a", encoding="ascii") as out:  # held open, like an encoder's output
    while True:
        out.write("x")
        out.flush()
        time.sleep(0.02)
"""


def test_cancel_kills_tools_started_through_a_shim(tmp_path: Path) -> None:
    output = tmp_path / "render.mp4"
    cancel = threading.Event()
    threading.Timer(0.8, cancel.set).start()
    with pytest.raises(ToolCancelled):
        run_tool([sys.executable, "-c", SHIM, TOOL, str(output)], timeout_s=30, cancel=cancel)
    # The grandchild is gone: the file stops growing and can be deleted (Windows refuses
    # to delete a file another process still has open).
    deadline = time.monotonic() + 5
    while True:
        size = output.stat().st_size
        time.sleep(0.3)
        if output.stat().st_size == size:
            break
        assert time.monotonic() < deadline, "the tool started by the shim kept running"
    assert size > 0
    output.unlink()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS tool-parent lifetime guard")
def test_hard_worker_exit_stops_its_media_tool(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("macOS tool-parent lifetime guard")
    import contextlib
    import os
    import signal

    output, group_file = tmp_path / "partial.mp4", tmp_path / "tool-group"
    parent_code = (
        "import sys\nfrom pathlib import Path\n"
        "from openworld_moments.media.process import run_tool\n"
        "run_tool([sys.executable, '-c', sys.argv[1], sys.argv[2]], timeout_s=60, "
        "on_spawn=lambda proc: Path(sys.argv[3]).write_text(str(proc.pid)))"
    )
    parent = subprocess.Popen(  # noqa: S603 - argument arrays, generated fixtures
        [PY, "-c", parent_code, TOOL, str(output), str(group_file)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert output.exists(), "media tool did not start"
        parent.kill()  # real SIGKILL: no worker finally/atexit hooks can run
        parent.wait(timeout=5)
        time.sleep(0.3)
        size = output.stat().st_size
        time.sleep(0.5)
        assert output.stat().st_size == size, "orphan media tool kept writing after worker exit"
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)
        if group_file.exists():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(int(group_file.read_text()), signal.SIGKILL)
        if parent.stderr is not None:
            parent.stderr.close()


@pytest.mark.parametrize("_attempt", range(5))
def test_cancel_at_spawn_never_leaves_an_output_pipe_open(_attempt: int) -> None:
    # Exercise the guard startup window before the actual media tool has started.
    cancel = threading.Event()
    spawned: list[subprocess.Popen[bytes]] = []

    def at_spawn(proc: subprocess.Popen[bytes]) -> None:
        spawned.append(proc)
        cancel.set()

    started = time.monotonic()
    with pytest.raises(ToolCancelled):
        run_tool([PY, "-c", SLEEP], timeout_s=60, cancel=cancel, on_spawn=at_spawn)
    assert time.monotonic() - started < 5
    assert spawned[0].poll() is not None
