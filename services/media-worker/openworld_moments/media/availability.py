# SPDX-License-Identifier: AGPL-3.0-or-later
"""Metadata-only cloud checks. Never open a placeholder to discover its state.

macOS SF_DATALESS is defined in sys/stat.h (Apple TN3150); Windows uses
OFFLINE / RECALL_ON_OPEN / RECALL_ON_DATA_ACCESS. Zero allocated blocks alone
do not imply a cloud file: ordinary sparse files are valid inputs.
"""

from __future__ import annotations

import os

SF_DATALESS = 0x40000000
WINDOWS_CLOUD_ATTRIBUTES = 0x1000 | 0x40000 | 0x400000
DOWNLOAD_REQUIRED = (
    "Download this item in Finder or OneDrive, wait for it to finish, then try again."
)


def cloud_only(info: os.stat_result) -> bool:
    return bool(
        getattr(info, "st_flags", 0) & SF_DATALESS
        or getattr(info, "st_file_attributes", 0) & WINDOWS_CLOUD_ATTRIBUTES
    )
