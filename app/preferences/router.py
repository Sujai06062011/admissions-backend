import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.core import AdminUser, Program
from app.models.stage1 import Application
from app.models.stage2 import AdminDecision, PreferenceConfig, PreferenceMatchResult
from app.preferences.matching import compute_preference_match
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

    return (
        db.query(PreferenceConfig)
        .filter(PreferenceConfig.program_id == program_id)
        .order_by(PreferenceConfig.created_at)
        .all()
    )


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


@router.post("/admin-decisions", response_model=AdminDecisionResponse, status_code=201)
def create_admin_decision(
    payload: AdminDecisionCreate, db: Session = Depends(get_db)
) -> AdminDecision:
    application = db.get(Application, payload.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if payload.decided_by is not None and db.get(AdminUser, payload.decided_by) is None:
        raise HTTPException(status_code=404, detail="Admin user not found")

    decision = AdminDecision(**payload.model_dump())
    db.add(decision)

    _apply_status_transition(application, payload.stage, payload.decision)

    db.commit()
    db.refresh(decision)
    return decision


def _apply_status_transition(application: Application, stage: str, decision: str) -> None:
    """Advances application.status to match an admin decision.

    'approved' and 'manual_override' both push the application forward for its
    stage; 'rejected' ends the pipeline regardless of stage. Adjust here if the
    intended state machine differs.
    """
    if decision == "rejected":
        application.status = "rejected"
    elif decision in ("approved", "manual_override"):
        if stage == "stage2_move_to_campus":
            application.status = "moved_to_campus"
        elif stage == "stage3_call_for_interview":
            application.status = "called_for_interview"
