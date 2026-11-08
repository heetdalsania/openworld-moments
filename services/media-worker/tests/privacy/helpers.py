# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit creator acknowledgment for synthetic test projects, never production code."""

from openworld_moments.privacy.service import PrivacyReviewService, ReviewChange
from openworld_moments.storage import Database


def acknowledge(database: Database, project_id: str) -> None:
    service = PrivacyReviewService(database)
    report = service.get(project_id)
    service.decide(
        project_id,
        ReviewChange.model_validate(
            dict(
                token=report["token"],
                acknowledged=True,
                decisions=[dict(id=f["id"], state="acknowledge") for f in report["flags"]],
            )
        ),
    )
