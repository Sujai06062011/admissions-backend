"""Group Discussion admin routes.

Additive only — does not change Application.status or existing pipeline endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_admin
from app.db.session import get_db
from app.group_discussion.artifacts import ingest_session_artifacts
from app.group_discussion.assignment import pick_participants
from app.group_discussion.eligibility import list_eligible_applications
from app.group_discussion.score_runner import score_session_participants
from app.group_discussion.schemas import (
    AssignGdSessionRequest,
    CreateGdSessionRequest,
    EligibleCandidateResponse,
    GdSessionResponse,
    SendInvitesResponse,
    SmokeCreateMeetingRequest,
    SmokeCreateMeetingResponse,
    UploadTranscriptRequest,
)
from app.group_discussion.service import serialize_session
from app.group_discussion.teams_graph import (
    TeamsGraphApiError,
    TeamsGraphConfig,
    TeamsGraphConfigError,
    create_online_meeting,
    enable_meeting_recording,
    teams_graph_enabled,
    vtt_to_plain_text,
)
from app.models.core import AdminUser, Program
from app.models.final import Notification
from app.models.group_discussion import GdParticipant, GdSession
from app.models.stage1 import Application
from app.notifications.email_dispatch import send_gd_invite_email
from app.preferences.matching import normalized_test_b_score

router = APIRouter(prefix="/admin/group-discussion", tags=["group_discussion"])


def _session_query(db: Session, session_id: uuid.UUID) -> GdSession | None:
    return db.execute(
        select(GdSession)
        .where(GdSession.id == session_id)
        .options(
            selectinload(GdSession.participants)
            .selectinload(GdParticipant.application)
            .selectinload(Application.applicant),
            selectinload(GdSession.participants)
            .selectinload(GdParticipant.application)
            .selectinload(Application.profile_data),
            selectinload(GdSession.participants)
            .selectinload(GdParticipant.application)
            .selectinload(Application.preference_match_result),
        )
    ).scalar_one_or_none()


def _replace_participants(db: Session, session: GdSession, apps: list[Application]) -> None:
    session.participants.clear()
    db.flush()
    for app in apps:
        session.participants.append(
            GdParticipant(application_id=app.id, role="candidate", invite_status="pending")
        )
    session.updated_at = datetime.now(timezone.utc)


# --- Smoke (unchanged behaviour) -------------------------------------------------


@router.post("/smoke/create-meeting", response_model=SmokeCreateMeetingResponse)
def smoke_create_meeting(
    payload: SmokeCreateMeetingRequest,
    _admin: AdminUser = Depends(get_current_admin),
) -> SmokeCreateMeetingResponse:
    if not teams_graph_enabled():
        raise HTTPException(
            status_code=503,
            detail="Teams Graph is disabled. Set TEAMS_GRAPH_ENABLED=true to run smoke tests.",
        )
    try:
        config = TeamsGraphConfig.from_env()
        meeting = create_online_meeting(
            subject=payload.subject,
            start=payload.start,
            duration_minutes=payload.duration_minutes,
            config=config,
        )
    except TeamsGraphConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TeamsGraphApiError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Microsoft Graph error ({exc.status_code}): {exc.body}",
        ) from exc

    return SmokeCreateMeetingResponse(
        meeting_id=meeting.meeting_id,
        join_url=meeting.join_url,
        subject=meeting.subject,
        start_date_time=meeting.start_date_time,
        end_date_time=meeting.end_date_time,
        organizer_upn=config.organizer_upn,
    )


# --- Eligible pool ----------------------------------------------------------------


@router.get("/eligible", response_model=list[EligibleCandidateResponse])
def get_eligible(
    program_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[EligibleCandidateResponse]:
    apps = list_eligible_applications(db, program_id)
    apps.sort(
        key=lambda a: float(a.preference_match_result.composite_score)
        if a.preference_match_result and a.preference_match_result.composite_score is not None
        else float("-inf"),
        reverse=True,
    )
    out: list[EligibleCandidateResponse] = []
    for app in apps:
        data = app.profile_data.data if app.profile_data and isinstance(app.profile_data.data, dict) else {}
        gender = data.get("gender") if isinstance(data.get("gender"), str) else None
        out.append(
            EligibleCandidateResponse(
                application_id=app.id,
                applicant_name=app.applicant.full_name if app.applicant else None,
                applicant_email=app.applicant.email if app.applicant else None,
                application_number=app.application_number,
                composite_score=float(app.preference_match_result.composite_score)
                if app.preference_match_result and app.preference_match_result.composite_score is not None
                else None,
                gender=gender,
                test_a_score=float(app.test_a_session.score)
                if app.test_a_session and app.test_a_session.score is not None
                else None,
                test_b_score=normalized_test_b_score(
                    app.test_b_session.rubric_score if app.test_b_session else None
                ),
            )
        )
    return out


# --- Sessions ---------------------------------------------------------------------


@router.get("/sessions", response_model=list[GdSessionResponse])
def list_sessions(
    program_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[GdSessionResponse]:
    sessions = (
        db.execute(
            select(GdSession)
            .where(GdSession.program_id == program_id)
            .order_by(GdSession.created_at.desc())
            .options(
                selectinload(GdSession.participants)
                .selectinload(GdParticipant.application)
                .selectinload(Application.applicant),
                selectinload(GdSession.participants)
                .selectinload(GdParticipant.application)
                .selectinload(Application.profile_data),
                selectinload(GdSession.participants)
                .selectinload(GdParticipant.application)
                .selectinload(Application.preference_match_result),
            )
        )
        .scalars()
        .all()
    )
    return [serialize_session(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=GdSessionResponse)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    return serialize_session(session)


@router.post("/sessions", response_model=GdSessionResponse, status_code=201)
def create_session(
    payload: CreateGdSessionRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    program = db.get(Program, payload.program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")

    session = GdSession(
        program_id=payload.program_id,
        label=payload.label,
        target_size=payload.target_size,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        assignment_strategy=payload.assignment_strategy,
        status="draft",
        professor_email=payload.professor_email,
        created_by=admin.id,
    )
    db.add(session)
    db.flush()

    if payload.auto_assign or payload.application_ids:
        eligible = list_eligible_applications(db, payload.program_id)
        try:
            picked = pick_participants(
                eligible,
                strategy=payload.assignment_strategy,
                target_size=payload.target_size,
                application_ids=payload.application_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _replace_participants(db, session, picked)

    db.commit()
    session = _session_query(db, session.id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/assign", response_model=GdSessionResponse)
def assign_session(
    session_id: uuid.UUID,
    payload: AssignGdSessionRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if session.status not in {"draft", "meeting_ready"}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reassign participants when status is '{session.status}'",
        )

    strategy = payload.assignment_strategy or session.assignment_strategy
    target_size = payload.target_size or session.target_size
    session.assignment_strategy = strategy
    session.target_size = target_size

    # Allow re-picking current members: treat this session's apps as free
    current_ids = {p.application_id for p in session.participants}
    eligible = list_eligible_applications(db, session.program_id)
    # Re-include apps already on this session
    if current_ids:
        extras = (
            db.execute(
                select(Application)
                .where(Application.id.in_(current_ids))
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
        by_id = {a.id: a for a in eligible}
        for app in extras:
            by_id[app.id] = app
        eligible = list(by_id.values())

    try:
        picked = pick_participants(
            eligible,
            strategy=strategy,
            target_size=target_size,
            application_ids=payload.application_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Reset meeting if membership changed after a meeting was created
    if session.status == "meeting_ready":
        session.teams_meeting_id = None
        session.join_url = None
        session.status = "draft"

    _replace_participants(db, session, picked)
    db.commit()
    session = _session_query(db, session_id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/create-meeting", response_model=GdSessionResponse)
def create_session_meeting(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if not session.participants:
        raise HTTPException(status_code=400, detail="Assign participants before creating a meeting")
    if session.scheduled_at is None:
        raise HTTPException(status_code=400, detail="scheduled_at is required before creating a meeting")
    if session.status == "invited":
        raise HTTPException(status_code=400, detail="Invites already sent; create a new session to reschedule")
    if not teams_graph_enabled():
        raise HTTPException(
            status_code=503,
            detail="Teams Graph is disabled. Set TEAMS_GRAPH_ENABLED=true.",
        )

    label = session.label or f"Group Discussion {str(session.id)[:8]}"
    subject = f"Admit GD — {label}"
    try:
        meeting = create_online_meeting(
            subject=subject,
            start=session.scheduled_at,
            duration_minutes=session.duration_minutes,
        )
    except TeamsGraphConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TeamsGraphApiError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Microsoft Graph error ({exc.status_code}): {exc.body}",
        ) from exc

    session.teams_meeting_id = meeting.meeting_id
    session.join_url = meeting.join_url
    session.status = "meeting_ready"
    session.artifacts_status = "pending"
    session.updated_at = datetime.now(timezone.utc)
    db.commit()

    session = _session_query(db, session_id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/enable-recording", response_model=GdSessionResponse)
def enable_session_recording(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    """PATCH Teams meeting to auto-record + transcription (for meetings created earlier)."""
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if not session.teams_meeting_id:
        raise HTTPException(status_code=400, detail="Session has no Teams meeting yet")
    if not teams_graph_enabled():
        raise HTTPException(status_code=503, detail="Teams Graph is disabled.")

    try:
        enable_meeting_recording(session.teams_meeting_id)
    except TeamsGraphConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TeamsGraphApiError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Microsoft Graph error ({exc.status_code}): {exc.body}",
        ) from exc

    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    session = _session_query(db, session_id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/fetch-artifacts", response_model=GdSessionResponse)
def fetch_session_artifacts(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    """After the meeting ends: pull recording → Supabase and transcript → DB.

    Poll Graph (recordings/transcripts appear a few minutes after the call).
    Webhooks can replace this later; this keeps the demo reliable without
    Azure change-notification setup.
    """
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if not session.teams_meeting_id:
        raise HTTPException(status_code=400, detail="Session has no Teams meeting yet")
    if not teams_graph_enabled():
        raise HTTPException(status_code=503, detail="Teams Graph is disabled.")

    try:
        session = ingest_session_artifacts(db, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # Supabase / unexpected
        session.artifacts_status = "failed"
        session.artifacts_error = str(exc)[:500]
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=502, detail=f"Artifact ingest failed: {exc}") from exc

    session = _session_query(db, session_id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/upload-transcript", response_model=GdSessionResponse)
def upload_session_transcript(
    session_id: uuid.UUID,
    payload: UploadTranscriptRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    """Store transcript text when Graph transcript API is still tenant-blocked.

    Download VTT from Stream (Transcript → Download), or paste plain text.
    Does not change Application.status.
    """
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")

    raw = payload.transcript.strip()
    if payload.is_vtt or raw.lstrip().startswith("WEBVTT"):
        session.transcript_vtt = raw
        session.transcript_text = vtt_to_plain_text(raw) or raw
    else:
        session.transcript_text = raw
        session.transcript_vtt = None

    session.transcript_graph_id = None
    session.artifacts_status = "ready"
    # Keep prior recording error note only if video missing
    if session.recording_storage_path:
        session.artifacts_error = None
    session.artifacts_fetched_at = datetime.now(timezone.utc)
    if session.status in {"invited", "meeting_ready", "draft"}:
        session.status = "completed"
    session.updated_at = datetime.now(timezone.utc)
    db.commit()

    session = _session_query(db, session_id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/score", response_model=GdSessionResponse)
def score_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    """Claude GDPI scoring per participant from stored transcript.

    Dimensions (0-10): leadership, communication, teamwork, attitude, content,
    grammar. overall_score is the equal-weight average on 0-10 (show as X/10
    in UI). For composite later, use overall_score * 10 → 0-100.
    Speakers are matched to applicants by name; unmatched speakers are skipped.
    """
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if not (session.transcript_text or session.transcript_vtt):
        raise HTTPException(status_code=400, detail="Fetch or upload a transcript before scoring")

    try:
        score_session_participants(db, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session = _session_query(db, session_id)
    assert session is not None
    return serialize_session(session)


@router.post("/sessions/{session_id}/send-invites", response_model=SendInvitesResponse)
def send_invites(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SendInvitesResponse:
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if not session.join_url:
        raise HTTPException(status_code=400, detail="Create a Teams meeting before sending invites")
    if session.scheduled_at is None:
        raise HTTPException(status_code=400, detail="scheduled_at is required")
    if not session.participants:
        raise HTTPException(status_code=400, detail="No participants to invite")

    program = db.get(Program, session.program_id)
    program_name = program.name if program else "Program"
    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for p in session.participants:
        app = p.application
        applicant = app.applicant if app else None
        email_ok, detail = send_gd_invite_email(
            to_email=applicant.email if applicant else None,
            applicant_name=applicant.full_name if applicant else None,
            program_name=program_name,
            session_label=session.label or "Group Discussion",
            scheduled_at=session.scheduled_at,
            duration_minutes=session.duration_minutes,
            join_url=session.join_url,
            application_number=app.application_number if app else None,
        )
        p.invite_status = "sent" if email_ok else "failed"
        p.invite_sent_at = now if email_ok else p.invite_sent_at
        db.add(
            Notification(
                application_id=p.application_id,
                channel="email",
                type="gd_invite",
                status="sent" if email_ok else "failed",
            )
        )
        results.append(
            {
                "application_id": str(p.application_id),
                "email": applicant.email if applicant else None,
                "success": email_ok,
                "detail": detail,
            }
        )

    session.status = "invited"
    session.updated_at = now
    db.commit()

    return SendInvitesResponse(session_id=session_id, status=session.status, results=results)
