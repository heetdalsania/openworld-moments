# OpenWorld Moments media worker

Python 3.12 package for media analysis. In M00 it contains only a health
function; see [MILESTONES.md](../../MILESTONES.md) for what arrives next.

Licensed under AGPL-3.0-or-later.

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```
