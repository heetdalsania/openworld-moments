# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite persistence: migrations, backups, health, and typed repositories (M02).

See docs/architecture/storage.md for what lives in SQLite versus on disk.
"""

from openworld_moments.storage.database import (
    Database,
    DatabaseHealth,
    Migration,
    MigrationError,
    MigrationReport,
    StorageError,
    transaction,
    utc_now,
)
from openworld_moments.storage.repositories import (
    AssetRepository,
    ConflictError,
    EventRepository,
    InUseError,
    JobRepository,
    NotFoundError,
    Session,
    SessionAsset,
    SessionRepository,
    SettingsRepository,
    Story,
    StoryRepository,
)

__all__ = [
    "AssetRepository",
    "ConflictError",
    "Database",
    "DatabaseHealth",
    "EventRepository",
    "InUseError",
    "JobRepository",
    "Migration",
    "MigrationError",
    "MigrationReport",
    "NotFoundError",
    "Session",
    "SessionAsset",
    "SessionRepository",
    "SettingsRepository",
    "StorageError",
    "Story",
    "StoryRepository",
    "transaction",
    "utc_now",
]
