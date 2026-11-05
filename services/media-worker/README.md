# OpenWorld Moments media worker

Python 3.12 package for media analysis. It currently contains SQLite storage
([storage guide](../../docs/architecture/storage.md)) and the worker process:
a loopback, token-protected API with a durable job engine
([worker guide](../../docs/architecture/worker.md)). See
[MILESTONES.md](../../MILESTONES.md) for what arrives next.

The desktop app starts the worker itself. To run it by hand:

```bash
python -c "import secrets; print(secrets.token_hex(32))" | uv run python -m openworld_moments.worker --library /tmp/owm-library
```

Licensed under AGPL-3.0-or-later.

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```
