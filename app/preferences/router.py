import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_admin
from app.campus.assignment import CampusFullyBooked, NoCampusSchedulesConfigured, assign_campus_session
from app.credentials.generation import generate_credentials
from app.db.session import get_db
from app.models.core import AdminUser, Program
from app.models.final import FinalDecision
from app.models.stage1 import Application
from app.models.stage2 import AdminDecision, PreferenceConfig, PreferenceMatchResult
from app.notifications.invite import send_campus_invite
from app.preferences.matching import compute_preference_match, ensure_gd_score_preference
from app.preferences.schemas import (
    ApplicationMatchResultItem,
    PreferenceConfigCreate,
    PreferenceConfigResponse,
)
from app.schemas.stage1 import ApplicationResponse
from app.schemas.stage2 import (
    AdminDecisionCreate,
    AdminDecisionResponse,
    PreferenceMatchResultResponse,
)

router = APIRouter(tags=["preferences"])


@router.post(
    "/programs/{program_id}/preference-configs",
    response_model=PreferenceConfigResponse,
    status_code=201,
)
def create_preference_config(
    program_id: uuid.UUID, payload: PreferenceConfigCreate, db: Session = Depends(get_db)
) -> PreferenceConfig:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    config = PreferenceConfig(program_id=program_id, **payload.model_dump())
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.get(
    "/programs/{program_id}/preference-configs",
    response_model=list[PreferenceConfigResponse],
)
def list_preference_configs(
    program_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[PreferenceConfig]:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    # Seed GD at 10% for programs that predate this field so Preferences UI
    # and composite scoring both see a real PreferenceConfig row. When we
    # insert for the first time, recompute matches so composites pick up GD.
    had_gd = (
        db.query(PreferenceConfig)
        .filter(
            PreferenceConfig.program_id == program_id,
            PreferenceConfig.field_name == "gd_score",
        )
        .first()
        is not None
    )
    ensure_gd_score_preference(db, program_id)
    if not had_gd:
        applications = db.query(Application).filter(Application.program_id == program_id).all()
        for application in applications:
            compute_preference_match(db, application)
    db.commit()

    return (
        db.query(PreferenceConfig)
        .filter(PreferenceConfig.program_id == program_id)
        .order_by(PreferenceConfig.created_at)
        .all()
    )


@router.put(
    "/programs/{program_id}/preference-configs",
    response_model=list[PreferenceConfigResponse],
)
def replace_preference_configs(
    program_id: uuid.UUID,
    payload: list[PreferenceConfigCreate],
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> list[PreferenceConfig]:
    """Atomically replaces every PreferenceConfig row for this program.

    There's no per-row PATCH: compute_preference_match sums every matching
    row for a field_name with no dedup, so editing in place by deleting +
    recreating the full set (rather than adding alongside old rows) is the
    only way to change weights without double-counting a field for every
    applicant. Existing applications are re-scored immediately afterwards so
    the new weights are reflected right away, not just for future
    submissions.
    """
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    db.query(PreferenceConfig).filter(PreferenceConfig.program_id == program_id).delete(
        synchronize_session=False
    )
    configs = [PreferenceConfig(program_id=program_id, **item.model_dump()) for item in payload]
    db.add_all(configs)
    db.flush()

    applications = db.query(Application).filter(Application.program_id == program_id).all()
    for application in applications:
        compute_preference_match(db, application)

    db.commit()
    for config in configs:
        db.refresh(config)
    return configs


@router.post(
    "/applications/{application_id}/compute-match",
    response_model=PreferenceMatchResultResponse,
)
def compute_match_for_application(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> PreferenceMatchResult:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    result = compute_preference_match(db, application)
    db.commit()
    db.refresh(result)
    return result


@router.get("/preference-match-results", response_model=list[ApplicationMatchResultItem])
def list_applications_with_match_results(
    db: Session = Depends(get_db),
    program_id: uuid.UUID | None = Query(None),
    hard_pass: bool | None = Query(
        None, description="True = passed all cutoffs, False = rejected by a hard cutoff"
    ),
    sort: Literal["asc", "desc"] = Query("desc", description="Order by composite_score"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
) -> list[ApplicationMatchResultItem]:
    query = db.query(Application).outerjoin(
        PreferenceMatchResult, Application.id == PreferenceMatchResult.application_id
    )

    if program_id is not None:
        query = query.filter(Application.program_id == program_id)
    if hard_pass is not None:
        query = query.filter(PreferenceMatchResult.hard_pass == hard_pass)

    score_col = PreferenceMatchResult.composite_score
    order = score_col.desc().nulls_last() if sort == "desc" else score_col.asc().nulls_last()

    applications = query.order_by(order).offset(offset).limit(limit).all()

    return [
        ApplicationMatchResultItem(
            application=ApplicationResponse.model_validate(app),
            match_result=(
                PreferenceMatchResultResponse.model_validate(app.preference_match_result)
                if app.preference_match_result
                else None
            ),
        )
        for app in applications
    ]


@router.get("/admin-decisions", response_model=list[AdminDecisionResponse])
def list_admin_decisions(
    db: Session = Depends(get_db),
    program_id: uuid.UUID | None = Query(None),
    decision: Literal["approved", "rejected", "manual_override"] | None = Query(None),
) -> list[AdminDecision]:
    """Lets the frontend cross-reference which applications have a decision
    of a given kind (e.g. manual_override, to highlight screening overrides
    in the Applications table) without fetching each candidate's full
    profile one at a time."""
    query = db.query(AdminDecision)
    if program_id is not None:
        query = query.join(Application, AdminDecision.application_id == Application.id).filter(
            Application.program_id == program_id
        )
    if decision is not None:
        query = query.filter(AdminDecision.decision == decision)
    return query.order_by(AdminDecision.decided_at.desc()).all()


@router.post("/admin-decisions", response_model=AdminDecisionResponse, status_code=201)
def create_admin_decision(
    payload: AdminDecisionCreate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> AdminDecision:
    application = db.get(Application, payload.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    decision = AdminDecision(**payload.model_dump(), decided_by=admin.id)
    db.add(decision)

    _apply_status_transition(application, payload.stage, payload.decision)

    if application.status == "moved_to_campus":
        try:
            campus_session = assign_campus_session(db, application)
        except NoCampusSchedulesConfigured:
            raise HTTPException(
                status_code=404,
                detail="No campus schedules configured for this program yet — add campus dates before moving applications to campus",
            )
        except CampusFullyBooked:
            raise HTTPException(
                status_code=409,
                detail="All campus schedules for this program are fully booked — add more dates",
            )

        credential, plaintext_password = generate_credentials(db, application)
        send_campus_invite(db, application, credential, plaintext_password, campus_session)

    if application.status == "offered":
        final = db.get(FinalDecision, application.id)
        if final is None:
            final = FinalDecision(application_id=application.id)
            db.add(final)
        final.decision = "offered"
        final.decided_by = admin.id
        final.decided_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(decision)
    return decision


def _apply_status_transition(application: Application, stage: str, decision: str) -> None:
    """Advances application.status to match an admin decision.

    'approved' always pushes the application forward for its stage;
    'rejected' ends the pipeline regardless of stage.

    'manual_override' at stage2_move_to_campus is deliberately NOT the same
    as 'approved' here: it only clears the hard-cutoff rejection so the
    candidate reappears in the normal Passed Screening pool — this leaves
    application.status untouched. The frontend (see the isOverridden
    parameter threaded through deriveStage/attachMatchResults in
    lib/adminPipeline.ts) is what actually reclassifies the candidate into
    the passed-screening bucket for display, since match_result.hard_pass
    alone would otherwise keep showing them as rejected forever — hard_pass
    is an objective computed fact this override doesn't change. Actually
    moving them to campus (session assignment, credentials, invite email)
    then requires a separate, deliberate "Move to Campus Test" click — the
    exact same action and code path every other passed candidate goes
    through — rather than firing automatically as a side effect of the
    override itself. A manual_override at any other stage (not currently
    reachable from the admin UI) still pushes forward immediately, same as
    'approved', since there's no equivalent holding pool built for it yet.
    """
    if decision == "rejected":
        application.status = "rejected"
    elif decision == "manual_override" and stage == "stage2_move_to_campus":
        return
    elif decision in ("approved", "manual_override"):
        if stage == "stage2_move_to_campus":
            application.status = "moved_to_campus"
        elif stage == "stage_group_discussion":
            application.status = "group_discussion"
        elif stage == "stage3_call_for_interview":
            application.status = "called_for_interview"
        elif stage == "stage4_offer":
            application.status = "offered"
