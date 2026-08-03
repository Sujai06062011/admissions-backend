"""Eligibility for Group Discussion — read-only over existing application data.

Eligible when Campus Test + Video Interview scores exist and the candidate is
still on campus statuses. Does not change Application.status.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.group_discussion import GdParticipant, GdSession
from app.models.stage1 import Application
from app.preferences.matching import normalized_test_b_score

ACTIVE_GD_STATUSES = ("draft", "meeting_ready", "invited")
ELIGIBLE_APP_STATUSES = ("moved_to_campus", "testing_complete")


def has_both_campus_scores(application: Application) -> bool:
    if application.test_a_session is None or application.test_a_session.score is None:
        return False
    if application.test_b_session is None:
        return False
    return normalized_test_b_score(application.test_b_session.rubric_score) is not None


def application_in_active_gd(db: Session, application_id: uuid.UUID) -> bool:
    row = db.execute(
        select(GdParticipant.id)
        .join(GdSession, GdSession.id == GdParticipant.gd_session_id)
        .where(
            GdParticipant.application_id == application_id,
            GdSession.status.in_(ACTIVE_GD_STATUSES),
        )
        .limit(1)
    ).first()
    return row is not None


def list_eligible_applications(db: Session, program_id: uuid.UUID) -> list[Application]:
    apps = (
        db.execute(
            select(Application)
            .where(
                Application.program_id == program_id,
                Application.status.in_(ELIGIBLE_APP_STATUSES),
            )
            .options(
                selectinload(Application.applicant),
                selectinload(Application.profile_data),
                selectinload(Application.preference_match_result),
                selectinload(Application.test_a_session),
                selectinload(Application.test_b_session),
            )
        )
        .scalars()
        .all()
    )

    active_ids = set(
        db.execute(
            select(GdParticipant.application_id)
            .join(GdSession, GdSession.id == GdParticipant.gd_session_id)
            .where(
                GdSession.program_id == program_id,
                GdSession.status.in_(ACTIVE_GD_STATUSES),
            )
        )
        .scalars()
        .all()
    )

    return [
        app
        for app in apps
        if has_both_campus_scores(app) and app.id not in active_ids
    ]
