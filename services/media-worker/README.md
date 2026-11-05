# OpenWorld Moments media worker

Python 3.12 package for media analysis. It currently contains a health
function and SQLite storage (migrations, backups, repositories); see
[docs/architecture/storage.md](../../docs/architecture/storage.md) and
[MILESTONES.md](../../MILESTONES.md) for what arrives next.

Licensed under AGPL-3.0-or-later.

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```
