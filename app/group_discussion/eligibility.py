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

ACTIVE_GD_STATUSES = ("draft", "meeting_ready", "invited", "live")
ELIGIBLE_APP_STATUSES = ("moved_to_campus", "testing_complete", "group_discussion")


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


def load_pack_pool(
    db: Session,
    program_id: uuid.UUID,
    application_ids: list[uuid.UUID],
) -> list[Application]:
    """Load specific applications for packing; validate campus scores + not in active GD."""
    if not application_ids:
        raise ValueError("application_ids is required")

    apps = (
        db.execute(
            select(Application)
            .where(
                Application.program_id == program_id,
                Application.id.in_(application_ids),
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
    by_id = {app.id: app for app in apps}
    missing = [str(i) for i in application_ids if i not in by_id]
    if missing:
        raise ValueError(f"Applications not found in this program: {', '.join(missing)}")

    bad_status = [
        str(i)
        for i in application_ids
        if by_id[i].status
        not in ("moved_to_campus", "testing_complete", "group_discussion")
    ]
    if bad_status:
        raise ValueError(
            "Applications must be on campus or group_discussion status: "
            + ", ".join(bad_status)
        )

    no_scores = [str(i) for i in application_ids if not has_both_campus_scores(by_id[i])]
    if no_scores:
        raise ValueError(
            "Applications need both Campus Test and Video Interview scores: "
            + ", ".join(no_scores)
        )

    busy = [
        str(i)
        for i in application_ids
        if application_in_active_gd(db, i)
    ]
    if busy:
        raise ValueError(
            "Applications already assigned to an active GD session: " + ", ".join(busy)
        )

    # Preserve requested order (caller may have shuffled).
    return [by_id[i] for i in application_ids]


def eligible_response_for(app: Application) -> dict:
    data = app.profile_data.data if app.profile_data and isinstance(app.profile_data.data, dict) else {}
    gender = data.get("gender") if isinstance(data.get("gender"), str) else None
    return {
        "application_id": app.id,
        "applicant_name": app.applicant.full_name if app.applicant else None,
        "applicant_email": app.applicant.email if app.applicant else None,
        "application_number": app.application_number,
        "composite_score": float(app.preference_match_result.composite_score)
        if app.preference_match_result and app.preference_match_result.composite_score is not None
        else None,
        "gender": gender,
        "test_a_score": float(app.test_a_session.score)
        if app.test_a_session and app.test_a_session.score is not None
        else None,
        "test_b_score": normalized_test_b_score(
            app.test_b_session.rubric_score if app.test_b_session else None
        ),
    }