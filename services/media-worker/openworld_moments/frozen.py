# SPDX-License-Identifier: AGPL-3.0-or-later
"""Console bootloader entrypoint preserves the existing stdin/stdout supervisor protocol."""

from __future__ import annotations

import json
import sys

from openworld_moments.system import configure_bundle


def main() -> int:
    try:
        configure_bundle()
    except (OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "event": "error",
                    "code": "worker.bundle_corrupt",
                    "message": "Packaged runtime verification failed. Repair the application.",
                }
            ),
            flush=True,
        )
        return 3
    if sys.argv[1:] == ["--purge-library"]:
        from openworld_moments.uninstall import purge_library

        try:
            purge_library()
        except OSError:
            print("Library removal failed. Retained data can be removed manually.", file=sys.stderr)
            return 4
        return 0
    if sys.argv[1:3] == ["-m", "openworld_moments.worker"]:
        from openworld_moments.worker.__main__ import main as worker

        return worker(sys.argv[3:])
    if sys.argv[1:3] == ["-m", "openworld_moments.gateway"]:
        from openworld_moments.gateway.__main__ import main as gateway

        return gateway(sys.argv[3:])
    print("Unsupported packaged-worker entrypoint.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
