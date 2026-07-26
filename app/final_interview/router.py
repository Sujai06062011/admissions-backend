import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_admin
from app.db.session import get_db
from app.final_interview.schemas import (
    CallForInterviewRequest,
    CallForInterviewResponse,
    CallForInterviewResult,
    InterviewResponse,
    ScheduleInterviewRequest,
)
from app.models.core import AdminUser
from app.models.final import FinalDecision, Interview, Notification
from app.models.stage1 import Application
from app.notifications.email_dispatch import send_interview_invite_email

router = APIRouter(tags=["final_interview"])


@router.post("/call-for-interview", response_model=CallForInterviewResponse, status_code=201)
def call_for_interview(
    payload: CallForInterviewRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> CallForInterviewResponse:
    """Marks one or more applications as called for interview: upserts a
    FinalDecision row (decision='called_for_interview'), advances
    application.status to match, and ensures an Interview row exists
    (status='pending', not yet scheduled) so it's ready for the schedule
    endpoint below.

    A single shared decided_by (the authenticated admin) covers the whole
    batch — this is one admin acting on a set of applications, not a
    per-application field. Invalid individual application_ids don't abort
    the batch: each gets its own success/failure result so 49 good IDs
    aren't blocked by 1 bad one. Re-calling an already-called application is
    idempotent (just refreshes decided_at/decided_by), not an error.
    """
    results: list[CallForInterviewResult] = []
    now = datetime.now(timezone.utc)

    for application_id in payload.application_ids:
        application = db.get(Application, application_id)
        if application is None:
            results.append(
                CallForInterviewResult(
                    application_id=application_id, success=False, detail="Application not found"
                )
            )
            continue

        decision = db.get(FinalDecision, application_id)
        if decision is None:
            decision = FinalDecision(application_id=application_id)
            db.add(decision)
        decision.decision = "called_for_interview"
        decision.decided_by = admin.id
        decision.decided_at = now

        application.status = "called_for_interview"

        if db.get(Interview, application_id) is None:
            db.add(Interview(application_id=application_id, status="pending"))

        results.append(CallForInterviewResult(application_id=application_id, success=True))

    db.commit()
    return CallForInterviewResponse(results=results)


@router.post(
    "/applications/{application_id}/interview/schedule", response_model=InterviewResponse
)
def schedule_interview(
    application_id: uuid.UUID, payload: ScheduleInterviewRequest, db: Session = Depends(get_db)
) -> InterviewResponse:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    interview = db.get(Interview, application_id)
    if interview is None:
        raise HTTPException(
            status_code=404, detail="Application has not been called for interview yet"
        )

    interview.scheduled_at = payload.scheduled_at
    interview.status = "scheduled"

    applicant = application.applicant
    email_ok, _ = send_interview_invite_email(
        to_email=applicant.email if applicant else None,
        applicant_name=applicant.full_name if applicant else None,
        program_name=application.program.name,
        scheduled_at=payload.scheduled_at,
    )
    db.add(
        Notification(
            application_id=application_id,
            channel="email",
            type="interview_invite",
            status="sent" if email_ok else "failed",
        )
    )

    db.commit()
    db.refresh(interview)

    return InterviewResponse(
        application_id=interview.application_id,
        scheduled_at=interview.scheduled_at,
        status=interview.status,
    )
