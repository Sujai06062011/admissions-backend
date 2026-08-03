"""Candidate-facing GD join APIs (campus portal). No admin JWT — application_id authz."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.group_discussion.acs import AcsConfigError, acs_enabled, issue_voip_join_token
from app.group_discussion.join_window import join_opens_at, join_window_open, topic_visible
from app.group_discussion.schemas import AcsJoinResponse, CandidateAcsJoinRequest
from app.models.group_discussion import GdParticipant, GdSession
from app.models.stage1 import Application

router = APIRouter(prefix="/campus/group-discussion", tags=["campus_group_discussion"])


def _load_session(db: Session, session_id: uuid.UUID) -> GdSession | None:
    return db.execute(
        select(GdSession)
        .where(GdSession.id == session_id)
        .options(
            selectinload(GdSession.participants)
            .selectinload(GdParticipant.application)
            .selectinload(Application.applicant),
        )
    ).scalar_one_or_none()


@router.post("/sessions/{session_id}/acs-join", response_model=AcsJoinResponse)
def candidate_acs_join(
    session_id: uuid.UUID,
    payload: CandidateAcsJoinRequest,
    db: Session = Depends(get_db),
) -> AcsJoinResponse:
    """Mint ACS credentials for a candidate assigned to this online GD session.

    Join URL is returned only to the authenticated portal session caller — never email it.
    Topic is omitted until the host starts the discussion.
    """
    if not acs_enabled():
        raise HTTPException(
            status_code=503,
            detail="ACS is disabled. Set ACS_ENABLED=true and ACS_CONNECTION_STRING.",
        )

    session = _load_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if (session.track or "online") != "online":
        raise HTTPException(status_code=400, detail="This GD session is not an online session")
    if not session.join_url or not session.teams_meeting_id:
        raise HTTPException(status_code=400, detail="Meeting is not ready yet")
    if session.status in {"draft"}:
        raise HTTPException(status_code=400, detail="Session has not been invited yet")

    participant = next(
        (p for p in session.participants if p.application_id == payload.application_id),
        None,
    )
    if participant is None:
        raise HTTPException(status_code=403, detail="You are not assigned to this GD session")

    if not join_window_open(session):
        opens = join_opens_at(session)
        raise HTTPException(
            status_code=403,
            detail=(
                "Join opens "
                + (opens.isoformat() if opens else "when the session is scheduled")
                + f" ({session.join_opens_minutes_before or 10} minutes before start)."
            ),
        )

    app = participant.application
    applicant = app.applicant if app else None
    display_name = (
        payload.display_name
        or (applicant.full_name if applicant else None)
        or (app.application_number if app else None)
        or "Candidate"
    )

    try:
        creds = issue_voip_join_token()
    except AcsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface ACS SDK failures cleanly
        raise HTTPException(status_code=502, detail=f"ACS token error: {exc}") from exc

    ends_at = None
    if session.started_at is not None:
        ends_at = session.started_at + timedelta(minutes=session.duration_minutes or 60)

    return AcsJoinResponse(
        session_id=session.id,
        role="candidate",
        display_name=display_name,
        acs_user_id=creds.user_id,
        acs_token=creds.token,
        acs_token_expires_on=creds.expires_on,
        teams_meeting_id=session.teams_meeting_id,
        teams_join_url=session.join_url,
        status=session.status,
        scheduled_at=session.scheduled_at,
        join_opens_at=join_opens_at(session),
        started_at=session.started_at,
        ends_at=ends_at,
        topic=session.topic if topic_visible(session) else None,
        duration_minutes=session.duration_minutes,
    )
