"""Build candidate-facing GD status for the campus portal."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.group_discussion.join_window import join_opens_at, join_window_open, topic_visible
from app.models.group_discussion import GdParticipant, GdSession

# Sessions the portal should surface (newest first among these).
PORTAL_GD_STATUSES = (
    "draft",
    "meeting_ready",
    "invited",
    "live",
    "completed",
    "scored",
)


def find_gd_session_for_application(
    db: Session, application_id: uuid.UUID
) -> GdSession | None:
    return db.execute(
        select(GdSession)
        .join(GdParticipant, GdParticipant.gd_session_id == GdSession.id)
        .where(
            GdParticipant.application_id == application_id,
            GdSession.status.in_(PORTAL_GD_STATUSES),
        )
        .options(selectinload(GdSession.participants))
        .order_by(GdSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def build_candidate_gd_status(db: Session, application_id: uuid.UUID) -> dict | None:
    session = find_gd_session_for_application(db, application_id)
    if session is None:
        return None

    ends_at = None
    if session.started_at is not None:
        ends_at = session.started_at + timedelta(minutes=session.duration_minutes or 60)

    join_enabled = bool(
        session.join_url
        and (session.track or "online") == "online"
        and session.status in {"invited", "meeting_ready", "live"}
        and join_window_open(session)
    )

    return {
        "assigned": True,
        "session_id": session.id,
        "track": session.track or "online",
        "label": session.label,
        "scheduled_at": session.scheduled_at,
        "duration_minutes": session.duration_minutes,
        "status": session.status,
        "join_opens_at": join_opens_at(session),
        "join_opens_minutes_before": session.join_opens_minutes_before,
        "join_enabled": join_enabled,
        "started_at": session.started_at,
        "ends_at": ends_at,
        "ended_at": session.ended_at,
        "topic": session.topic if topic_visible(session) else None,
        "completed": session.status in {"completed", "scored"},
    }
