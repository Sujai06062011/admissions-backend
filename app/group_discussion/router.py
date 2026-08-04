"""Group Discussion admin routes.

Additive only — does not change Application.status or existing pipeline endpoints.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_admin
from app.credentials.generation import generate_credentials
from app.db.session import get_db
from app.group_discussion.acs import (
    AcsConfigError,
    acs_enabled,
    issue_voip_join_token,
)
from app.group_discussion.artifacts import ingest_session_artifacts
from app.group_discussion.assignment import pick_participants
from app.group_discussion.eligibility import (
    ACTIVE_GD_STATUSES,
    eligible_response_for,
    list_eligible_applications,
    load_pack_pool,
)
from app.group_discussion.packing import shuffle_pack
from app.group_discussion.join_window import (
    default_join_opens_minutes,
    join_opens_at,
    join_window_open,
    topic_visible,
)
from app.group_discussion.schemas import (
    AcsJoinResponse,
    AdminAcsJoinRequest,
    AssignGdSessionRequest,
    CreateGdSessionRequest,
    EligibleCandidateResponse,
    GdProgramSettingsResponse,
    GdSessionResponse,
    MoveGdParticipantsRequest,
    MoveGdParticipantsResponse,
    PackGdSessionsRequest,
    PackGdSessionsResponse,
    PackPreviewGroup,
    PackPreviewRequest,
    PackPreviewResponse,
    SendInvitesResponse,
    SmokeAcsTokenResponse,
    SmokeCreateMeetingRequest,
    SmokeCreateMeetingResponse,
    EndGdSessionResponse,
    StartGdSessionResponse,
    UpdateGdProgramSettingsRequest,
    UpdateGdSessionRequest,
    UploadTranscriptRequest,
)
from app.group_discussion.settings import get_or_default_settings, upsert_settings
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
from app.models.stage2 import AdminDecision
from app.notifications.email_dispatch import send_gd_invite_email, send_gd_moderator_invite_email
from app.preferences.matching import normalized_test_b_score
from app.group_discussion.score_runner import score_session_participants

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


REASSIGNABLE_STATUSES = frozenset({"draft", "meeting_ready"})


def _replace_participants(db: Session, session: GdSession, apps: list[Application]) -> None:
    session.participants.clear()
    db.flush()
    for app in apps:
        session.participants.append(
            GdParticipant(application_id=app.id, role="candidate", invite_status="pending")
        )
    session.target_size = max(len(apps), 2) if apps else session.target_size
    session.updated_at = datetime.now(timezone.utc)


def _reset_meeting_if_needed(session: GdSession) -> None:
    """Membership change invalidates a prepared Teams meeting."""
    if session.status == "meeting_ready":
        session.teams_meeting_id = None
        session.join_url = None
        session.status = "draft"


def _require_reassignable(session: GdSession, label: str = "session") -> None:
    if session.status not in REASSIGNABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reassign participants when {label} status is '{session.status}'",
        )


def _active_session_for_app(db: Session, application_id: uuid.UUID) -> GdSession | None:
    session_id = db.execute(
        select(GdParticipant.gd_session_id)
        .join(GdSession, GdSession.id == GdParticipant.gd_session_id)
        .where(
            GdParticipant.application_id == application_id,
            GdSession.status.in_(ACTIVE_GD_STATUSES),
        )
        .limit(1)
    ).scalar_one_or_none()
    if session_id is None:
        return None
    return _session_query(db, session_id)


def _load_applications(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Application]:
    if not ids:
        return {}
    apps = (
        db.execute(
            select(Application)
            .where(Application.id.in_(ids))
            .options(
                selectinload(Application.applicant),
                selectinload(Application.profile_data),
                selectinload(Application.preference_match_result),
            )
        )
        .scalars()
        .all()
    )
    return {a.id: a for a in apps}


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


@router.post("/smoke/acs-token", response_model=SmokeAcsTokenResponse)
def smoke_acs_token(
    _admin: AdminUser = Depends(get_current_admin),
) -> SmokeAcsTokenResponse:
    """Mint a short-lived ACS VoIP_JOIN token (no DB / no Teams meeting)."""
    if not acs_enabled():
        raise HTTPException(
            status_code=503,
            detail="ACS is disabled. Set ACS_ENABLED=true to run smoke tests.",
        )
    try:
        creds = issue_voip_join_token()
    except AcsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ACS token error: {exc}") from exc
    return SmokeAcsTokenResponse(
        user_id=creds.user_id,
        token=creds.token,
        expires_on=creds.expires_on,
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


# --- Program settings -------------------------------------------------------------


@router.get("/settings", response_model=GdProgramSettingsResponse)
def get_settings(
    program_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdProgramSettingsResponse:
    program = db.get(Program, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    row = get_or_default_settings(db, program_id)
    return GdProgramSettingsResponse(
        program_id=program_id,
        min_group_size=row.min_group_size,
        max_group_size=row.max_group_size,
        default_duration_minutes=row.default_duration_minutes,
    )


@router.put("/settings", response_model=GdProgramSettingsResponse)
def put_settings(
    payload: UpdateGdProgramSettingsRequest,
    program_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdProgramSettingsResponse:
    program = db.get(Program, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    try:
        row = upsert_settings(
            db,
            program_id,
            min_group_size=payload.min_group_size,
            max_group_size=payload.max_group_size,
            default_duration_minutes=payload.default_duration_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return GdProgramSettingsResponse(
        program_id=row.program_id,
        min_group_size=row.min_group_size,
        max_group_size=row.max_group_size,
        default_duration_minutes=row.default_duration_minutes,
    )


# --- Pack / multi-group create ----------------------------------------------------


@router.post("/pack/preview", response_model=PackPreviewResponse)
def pack_preview(
    payload: PackPreviewRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> PackPreviewResponse:
    settings = get_or_default_settings(db, payload.program_id)
    min_size = payload.min_size if payload.min_size is not None else settings.min_group_size
    max_size = payload.max_size if payload.max_size is not None else settings.max_group_size
    try:
        pool = load_pack_pool(db, payload.program_id, payload.application_ids)
        groups = shuffle_pack(
            pool, min_size=min_size, max_size=max_size, seed=payload.seed
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out_groups: list[PackPreviewGroup] = []
    for i, group in enumerate(groups):
        applicants = [
            EligibleCandidateResponse(**eligible_response_for(app)) for app in group
        ]
        out_groups.append(
            PackPreviewGroup(
                index=i,
                size=len(group),
                application_ids=[app.id for app in group],
                applicants=applicants,
            )
        )
    return PackPreviewResponse(
        min_size=min_size,
        max_size=max_size,
        total_candidates=len(pool),
        groups=out_groups,
    )


@router.post("/pack", response_model=PackGdSessionsResponse, status_code=201)
def pack_sessions(
    payload: PackGdSessionsRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> PackGdSessionsResponse:
    program = db.get(Program, payload.program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")

    settings = get_or_default_settings(db, payload.program_id)
    default_duration = settings.default_duration_minutes
    join_opens = default_join_opens_minutes()

    # Validate pool once across all groups (no duplicates, eligible).
    all_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for g in payload.groups:
        for aid in g.application_ids:
            if aid in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"Application {aid} appears in more than one group",
                )
            seen.add(aid)
            all_ids.append(aid)
    try:
        pool = load_pack_pool(db, payload.program_id, all_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    by_id = {app.id: app for app in pool}

    created_ids: list[uuid.UUID] = []
    for g in payload.groups:
        duration = g.duration_minutes if g.duration_minutes is not None else default_duration
        session = GdSession(
            program_id=payload.program_id,
            label=g.label,
            target_size=len(g.application_ids),
            scheduled_at=g.scheduled_at,
            duration_minutes=duration,
            assignment_strategy="manual",
            status="draft",
            track=payload.track,
            topic=g.topic,
            professor_email=g.professor_email,
            professor_name=g.professor_name,
            join_opens_minutes_before=join_opens,
            created_by=admin.id,
        )
        db.add(session)
        db.flush()
        apps = [by_id[aid] for aid in g.application_ids]
        _replace_participants(db, session, apps)

        if payload.track == "online" and payload.auto_create_meetings:
            if not teams_graph_enabled():
                raise HTTPException(
                    status_code=503,
                    detail="Teams Graph is disabled; cannot auto-create meetings.",
                )
            try:
                config = TeamsGraphConfig.from_env()
                start = g.scheduled_at or datetime.now(timezone.utc)
                meeting = create_online_meeting(
                    subject=g.label or "Group Discussion",
                    start=start,
                    duration_minutes=duration,
                    config=config,
                )
            except TeamsGraphConfigError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except (TeamsGraphApiError, ValueError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            session.teams_meeting_id = meeting.meeting_id
            session.join_url = meeting.join_url
            session.status = "meeting_ready"
        elif payload.track == "manual":
            session.status = "meeting_ready"

        if payload.move_status:
            for app in apps:
                app.status = "group_discussion"
                db.add(
                    AdminDecision(
                        application_id=app.id,
                        stage="stage_group_discussion",
                        decision="approved",
                        decided_by=admin.id,
                        notes=f"Packed into GD session {session.id}",
                    )
                )
        created_ids.append(session.id)

    db.commit()
    sessions = [_session_query(db, sid) for sid in created_ids]
    return PackGdSessionsResponse(
        sessions=[serialize_session(s) for s in sessions if s is not None]
    )


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

    join_opens = payload.join_opens_minutes_before
    if join_opens is None:
        join_opens = default_join_opens_minutes()

    session = GdSession(
        program_id=payload.program_id,
        label=payload.label,
        target_size=payload.target_size,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        assignment_strategy=payload.assignment_strategy,
        status="draft",
        track=payload.track,
        topic=payload.topic,
        professor_email=payload.professor_email,
        professor_name=payload.professor_name,
        join_opens_minutes_before=join_opens,
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


@router.patch("/sessions/{session_id}", response_model=GdSessionResponse)
def update_session(
    session_id: uuid.UUID,
    payload: UpdateGdSessionRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GdSessionResponse:
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if session.status in {"completed", "scored"}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update session when status is '{session.status}'",
        )

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(session, key, value)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    session = _session_query(db, session_id)
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


@router.post("/move-participants", response_model=MoveGdParticipantsResponse)
def move_participants(
    payload: MoveGdParticipantsRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> MoveGdParticipantsResponse:
    """Move or swap candidates across Online / In-person GD sessions (or unassign)."""
    move_ids = list(dict.fromkeys(payload.application_ids))
    apps_by_id = _load_applications(db, move_ids)
    missing = [str(i) for i in move_ids if i not in apps_by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Applications not found: {', '.join(missing)}")

    touched: dict[uuid.UUID, GdSession] = {}

    def touch(session: GdSession) -> None:
        touched[session.id] = session

    def membership_apps(session: GdSession) -> list[Application]:
        # Ensure participants collection is loaded
        ids = [p.application_id for p in session.participants]
        loaded = _load_applications(db, ids)
        # Preserve order; fall back if somehow missing
        return [loaded[i] for i in ids if i in loaded]

    # --- Swap (exactly one mover ↔ one partner) ---
    if payload.swap_with_application_id is not None:
        if len(move_ids) != 1:
            raise HTTPException(
                status_code=400,
                detail="Swap requires exactly one application_id",
            )
        if payload.to_session_id is None:
            raise HTTPException(
                status_code=400,
                detail="Swap requires to_session_id (partner's session)",
            )
        mover_id = move_ids[0]
        partner_id = payload.swap_with_application_id
        if mover_id == partner_id:
            raise HTTPException(status_code=400, detail="Cannot swap a candidate with themselves")

        partner_apps = _load_applications(db, [partner_id])
        if partner_id not in partner_apps:
            raise HTTPException(status_code=404, detail="Swap partner application not found")

        mover_session = _active_session_for_app(db, mover_id)
        partner_session = _active_session_for_app(db, partner_id)
        if partner_session is None:
            raise HTTPException(status_code=400, detail="Swap partner is not in an active GD session")
        if partner_session.id != payload.to_session_id:
            raise HTTPException(
                status_code=400,
                detail="to_session_id must be the swap partner's current session",
            )
        _require_reassignable(partner_session, "destination session")

        if mover_session is None:
            # Unassigned → take partner's seat; partner becomes unassigned
            partner_members = [
                a for a in membership_apps(partner_session) if a.id != partner_id
            ] + [apps_by_id[mover_id]]
            _reset_meeting_if_needed(partner_session)
            _replace_participants(db, partner_session, partner_members)
            touch(partner_session)
        else:
            if mover_session.id == partner_session.id:
                raise HTTPException(
                    status_code=400,
                    detail="Both candidates are already in the same session",
                )
            _require_reassignable(mover_session, "source session")
            mover_members = [
                a for a in membership_apps(mover_session) if a.id != mover_id
            ] + [partner_apps[partner_id]]
            partner_members = [
                a for a in membership_apps(partner_session) if a.id != partner_id
            ] + [apps_by_id[mover_id]]
            _reset_meeting_if_needed(mover_session)
            _reset_meeting_if_needed(partner_session)
            _replace_participants(db, mover_session, mover_members)
            _replace_participants(db, partner_session, partner_members)
            touch(mover_session)
            touch(partner_session)

        db.commit()
        return MoveGdParticipantsResponse(
            sessions=[
                serialize_session(s)
                for sid in touched
                if (s := _session_query(db, sid)) is not None
            ]
        )

    # --- Move into a session (or unassign) ---
    dest: GdSession | None = None
    if payload.to_session_id is not None:
        dest = _session_query(db, payload.to_session_id)
        if dest is None:
            raise HTTPException(status_code=404, detail="Destination GD session not found")
        _require_reassignable(dest, "destination session")
        touch(dest)

    settings = get_or_default_settings(db, dest.program_id) if dest else None

    # Resolve current sources (skip people already in destination)
    sources: dict[uuid.UUID, GdSession] = {}
    for aid in move_ids:
        src = _active_session_for_app(db, aid)
        if src is None:
            continue
        if dest is not None and src.id == dest.id:
            continue
        _require_reassignable(src, "source session")
        sources[src.id] = src
        touch(src)

    if dest is not None:
        dest_members = membership_apps(dest)
        dest_ids = {a.id for a in dest_members}
        projected = list(dest_members)
        for aid in move_ids:
            if aid not in dest_ids:
                projected.append(apps_by_id[aid])
                dest_ids.add(aid)
        if settings and len(projected) > settings.max_group_size:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Destination group would have {len(projected)} candidates "
                    f"(max {settings.max_group_size})"
                ),
            )

    # Remove movers from source sessions, then add to destination
    mover_set = set(move_ids)
    for src in sources.values():
        remaining = [a for a in membership_apps(src) if a.id not in mover_set]
        _reset_meeting_if_needed(src)
        _replace_participants(db, src, remaining)

    if dest is not None:
        dest_members = membership_apps(dest)
        dest_ids = {a.id for a in dest_members}
        for aid in move_ids:
            if aid not in dest_ids:
                dest_members.append(apps_by_id[aid])
                dest_ids.add(aid)
        _reset_meeting_if_needed(dest)
        _replace_participants(db, dest, dest_members)

    db.commit()
    return MoveGdParticipantsResponse(
        sessions=[
            serialize_session(s)
            for sid in touched
            if (s := _session_query(db, sid)) is not None
        ]
    )


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
    if (session.track or "online") == "online" and not session.join_url:
        raise HTTPException(status_code=400, detail="Create a Teams meeting before sending invites")
    if session.scheduled_at is None:
        raise HTTPException(status_code=400, detail="scheduled_at is required")
    if not session.participants:
        raise HTTPException(status_code=400, detail="No participants to invite")

    portal_base = os.environ.get(
        "CAMPUS_PORTAL_BASE_URL", "https://admissions-frontend-phi.vercel.app/campus"
    ).rstrip("/")
    portal_url = portal_base
    join_opens = session.join_opens_minutes_before or default_join_opens_minutes()

    program = db.get(Program, session.program_id)
    program_name = program.name if program else "Program"
    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for p in session.participants:
        app = p.application
        applicant = app.applicant if app else None
        if app is None:
            results.append(
                {
                    "application_id": str(p.application_id),
                    "email": None,
                    "success": False,
                    "detail": "application missing",
                }
            )
            continue

        credential, plaintext_password = generate_credentials(db, app)
        email_ok, detail = send_gd_invite_email(
            to_email=applicant.email if applicant else None,
            applicant_name=applicant.full_name if applicant else None,
            program_name=program_name,
            session_label=session.label or "Group Discussion",
            scheduled_at=session.scheduled_at,
            duration_minutes=session.duration_minutes,
            portal_url=portal_url,
            temp_username=credential.temp_username,
            temp_password=plaintext_password,
            application_number=app.application_number,
            join_opens_minutes_before=join_opens,
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
                "temp_username": credential.temp_username,
                "success": email_ok,
                "detail": detail,
            }
        )

    if session.professor_email and session.join_url:
        mod_ok, mod_detail = send_gd_moderator_invite_email(
            to_email=session.professor_email,
            moderator_name=session.professor_name,
            program_name=program_name,
            session_label=session.label or "Group Discussion",
            scheduled_at=session.scheduled_at,
            duration_minutes=session.duration_minutes,
            join_url=session.join_url,
        )
        results.append(
            {
                "application_id": None,
                "email": session.professor_email,
                "role": "moderator",
                "success": mod_ok,
                "detail": mod_detail,
            }
        )

    session.status = "invited"
    session.updated_at = now
    db.commit()

    return SendInvitesResponse(session_id=session_id, status=session.status, results=results)


@router.post("/sessions/{session_id}/start", response_model=StartGdSessionResponse)
def start_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> StartGdSessionResponse:
    """Host Start — reveals topic and starts the countdown clock."""
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if session.status not in {"invited", "meeting_ready", "live"}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start session when status is '{session.status}'",
        )
    if not session.topic:
        raise HTTPException(status_code=400, detail="Set topic before starting the GD")

    now = datetime.now(timezone.utc)
    if session.started_at is None:
        session.started_at = now
    session.status = "live"
    session.updated_at = now
    db.commit()

    ends_at = session.started_at + timedelta(minutes=session.duration_minutes or 60)
    return StartGdSessionResponse(
        session_id=session.id,
        status=session.status,
        started_at=session.started_at,
        ends_at=ends_at,
        topic=session.topic,
    )


@router.post("/sessions/{session_id}/end", response_model=EndGdSessionResponse)
def end_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> EndGdSessionResponse:
    """Host End — marks session completed so clients can hang up and show done state."""
    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if session.status in {"completed", "scored"}:
        ended = session.ended_at or datetime.now(timezone.utc)
        return EndGdSessionResponse(
            session_id=session.id, status=session.status, ended_at=ended
        )
    if session.status not in {"live", "invited", "meeting_ready"}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot end session when status is '{session.status}'",
        )

    now = datetime.now(timezone.utc)
    session.ended_at = now
    session.status = "completed"
    session.updated_at = now
    db.commit()
    return EndGdSessionResponse(
        session_id=session.id, status=session.status, ended_at=now
    )


@router.post("/sessions/{session_id}/acs-join", response_model=AcsJoinResponse)
def admin_acs_join(
    session_id: uuid.UUID,
    payload: AdminAcsJoinRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> AcsJoinResponse:
    """Admin/host ACS join credentials for an existing Teams meeting (FE-less testing)."""
    if not acs_enabled():
        raise HTTPException(
            status_code=503,
            detail="ACS is disabled. Set ACS_ENABLED=true and ACS_CONNECTION_STRING.",
        )

    session = _session_query(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="GD session not found")
    if not session.join_url or not session.teams_meeting_id:
        raise HTTPException(status_code=400, detail="Create a Teams meeting first")

    if (
        payload.role == "candidate"
        and not payload.bypass_join_window
        and not join_window_open(session)
    ):
        opens = join_opens_at(session)
        raise HTTPException(
            status_code=403,
            detail="Join window is closed. Opens at "
            + (opens.isoformat() if opens else "scheduled_at − join_opens_minutes_before"),
        )

    try:
        creds = issue_voip_join_token()
    except AcsConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ACS token error: {exc}") from exc

    ends_at = None
    if session.started_at is not None:
        ends_at = session.started_at + timedelta(minutes=session.duration_minutes or 60)

    return AcsJoinResponse(
        session_id=session.id,
        role=payload.role,
        display_name=payload.display_name,
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
        topic=session.topic if (payload.role == "host" or topic_visible(session)) else None,
        duration_minutes=session.duration_minutes,
    )
