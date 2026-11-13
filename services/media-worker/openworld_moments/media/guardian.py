# SPDX-License-Identifier: AGPL-3.0-or-later
"""macOS tool lifetime guard. EOF on the worker-owned pipe kills this session,
including the media tool, even when SIGKILL prevents worker cleanup. No daemon,
launch agent, persisted PID, shell, or network service is involved.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        return 2
    argv = sys.argv[1:] if argv is None else argv
    # Only kill a session this process owns; direct invocation must never signal
    # a terminal, app host, or another process group.
    if os.name != "posix" or os.getpgrp() != os.getpid() or not argv:
        return 2
    try:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True)  # noqa: S603
    except OSError:
        return 127

    def watch_parent() -> None:
        with contextlib.suppress(OSError):
            while os.read(0, 4096):
                pass
        os.killpg(os.getpid(), signal.SIGKILL)

    threading.Thread(target=watch_parent, daemon=True, name="tool-parent-watch").start()
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
