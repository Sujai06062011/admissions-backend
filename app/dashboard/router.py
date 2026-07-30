import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.applications.storage import create_document_signed_url
from app.dashboard.analytics import compute_funnel
from app.dashboard.schemas import (
    CandidateListItem,
    CandidateProfileResponse,
    FunnelResponse,
    SignedUrlResponse,
)
from app.db.session import get_db
from app.interview_engine.storage import create_recording_signed_url, create_snapshot_signed_url
from app.models.core import Program
from app.models.stage1 import Application, UploadedDocument
from app.models.stage3_test_b import TestBSession
from app.preferences.matching import compute_preference_match, normalized_test_b_score
from app.schemas.stage1 import ApplicantResponse, ApplicationResponse, ProfileDataResponse, UploadedDocumentResponse
from app.schemas.stage2 import AdminDecisionResponse, PreferenceMatchResultResponse
from app.schemas.stage3 import TestASessionResponse, TestBSessionResponse

router = APIRouter(tags=["dashboard"])


def _has_data_mismatch(profile_data) -> bool:
    """True when the candidate submitted after acknowledging OCR/name
    mismatches — profile_data.data["data_mismatches"] is written by the
    Confirm & Submit consent screen. Missing/empty means a clean submit.
    """
    if profile_data is None or not isinstance(profile_data.data, dict):
        return False
    mismatches = profile_data.data.get("data_mismatches")
    if not isinstance(mismatches, dict):
        return False
    names = mismatches.get("name_mismatches") or []
    edits = mismatches.get("edited_fields") or []
    return bool(names) or bool(edits)


# --- Funnel analytics ---


@router.get("/programs/{program_id}/funnel", response_model=FunnelResponse)
def get_funnel(program_id: uuid.UUID, db: Session = Depends(get_db)) -> FunnelResponse:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    counts = compute_funnel(db, program_id)
    return FunnelResponse(program_id=program_id, **counts)


# --- Candidate list ---


@router.get("/candidates", response_model=list[CandidateListItem])
def list_candidates(
    db: Session = Depends(get_db),
    program_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    sort_by: Literal["preference_match_score", "test_a_score", "test_b_score"] = Query(
        "preference_match_score"
    ),
    order: Literal["asc", "desc"] = Query("desc"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
) -> list[CandidateListItem]:
    query = db.query(Application).options(
        selectinload(Application.applicant),
        selectinload(Application.preference_match_result),
        selectinload(Application.test_a_session),
        selectinload(Application.test_b_session),
        selectinload(Application.profile_data),
    )
    if program_id is not None:
        query = query.filter(Application.program_id == program_id)
    if status is not None:
        query = query.filter(Application.status == status)

    items = []
    for app in query.all():
        proctoring_review = app.test_b_session.proctoring_review if app.test_b_session else None
        items.append(
            CandidateListItem(
                application_id=app.id,
                applicant_name=app.applicant.full_name if app.applicant else None,
                program_id=app.program_id,
                status=app.status,
                preference_match_score=(
                    app.preference_match_result.composite_score
                    if app.preference_match_result
                    else None
                ),
                test_a_score=app.test_a_session.score if app.test_a_session else None,
                test_b_score=normalized_test_b_score(
                    app.test_b_session.rubric_score if app.test_b_session else None
                ),
                proctoring_flagged=(
                    proctoring_review.get("flagged") if proctoring_review else None
                ),
                has_data_mismatch=_has_data_mismatch(app.profile_data),
            )
        )

    # Composed here in Python rather than pushed to SQL: test_b_score is a
    # derived average over a JSONB column, so all three sort keys are handled
    # the same way for consistent pagination behavior regardless of which one
    # is picked. Unscored candidates always sort last, in either direction.
    key_map = {
        "preference_match_score": lambda i: i.preference_match_score,
        "test_a_score": lambda i: i.test_a_score,
        "test_b_score": lambda i: i.test_b_score,
    }
    key_fn = key_map[sort_by]
    scored = [i for i in items if key_fn(i) is not None]
    unscored = [i for i in items if key_fn(i) is None]
    scored.sort(key=key_fn, reverse=(order == "desc"))

    return (scored + unscored)[offset : offset + limit]


# --- Candidate profile ---


@router.get("/candidates/{application_id}", response_model=CandidateProfileResponse)
def get_candidate_profile(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> CandidateProfileResponse:
    application = (
        db.query(Application)
        .options(
            selectinload(Application.applicant),
            selectinload(Application.profile_data),
            selectinload(Application.uploaded_documents),
            selectinload(Application.preference_match_result),
            selectinload(Application.admin_decisions),
            selectinload(Application.campus_session),
            selectinload(Application.test_a_session),
            selectinload(Application.test_b_session),
        )
        .filter(Application.id == application_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    # Recompute so Preference Match reflects live Campus Test / Video Interview
    # scores (heals older rows where Numeric Decimal scores were dropped).
    preference_match = compute_preference_match(db, application)
    db.commit()

    campus_session_response = None
    if application.campus_session is not None:
        cs = application.campus_session
        campus_session_response = {
            "application_id": cs.application_id,
            "schedule_id": cs.schedule_id,
            "session_date": cs.schedule.session_date,
            "slot_time": cs.slot_time,
            "check_in_status": cs.check_in_status,
            "device_id": cs.device_id,
        }

    return CandidateProfileResponse(
        application=ApplicationResponse.model_validate(application),
        applicant=ApplicantResponse.model_validate(application.applicant),
        profile_data=(
            ProfileDataResponse.model_validate(application.profile_data)
            if application.profile_data
            else None
        ),
        documents=[
            UploadedDocumentResponse.model_validate(d) for d in application.uploaded_documents
        ],
        preference_match=PreferenceMatchResultResponse.model_validate(preference_match),
        admin_decisions=[
            AdminDecisionResponse.model_validate(d) for d in application.admin_decisions
        ],
        campus_session=campus_session_response,
        test_a_session=(
            TestASessionResponse.model_validate(application.test_a_session)
            if application.test_a_session
            else None
        ),
        test_b_session=(
            TestBSessionResponse.model_validate(application.test_b_session)
            if application.test_b_session
            else None
        ),
    )


# --- Signed URLs ---


def _signed_url_response(url: str, expires_in: int) -> SignedUrlResponse:
    return SignedUrlResponse(
        url=url, expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    )


@router.get("/documents/{document_id}/signed-url", response_model=SignedUrlResponse)
def get_document_signed_url(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    expires_in: int = Query(3600, ge=60, le=86400, description="Seconds until the URL expires"),
) -> SignedUrlResponse:
    document = db.get(UploadedDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    url = create_document_signed_url(document.file_url, expires_in)
    return _signed_url_response(url, expires_in)


@router.get(
    "/applications/{application_id}/recording-signed-url", response_model=SignedUrlResponse
)
def get_recording_signed_url(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    expires_in: int = Query(3600, ge=60, le=86400, description="Seconds until the URL expires"),
) -> SignedUrlResponse:
    session = db.get(TestBSession, application_id)
    if session is None or not session.recording_url:
        raise HTTPException(status_code=404, detail="No recording found for this application")

    url = create_recording_signed_url(session.recording_url, expires_in)
    return _signed_url_response(url, expires_in)


@router.get(
    "/applications/{application_id}/proctoring-snapshot-signed-url",
    response_model=SignedUrlResponse,
)
def get_proctoring_snapshot_signed_url(
    application_id: uuid.UUID,
    path: str = Query(..., description="One of this session's snapshot_urls object paths"),
    db: Session = Depends(get_db),
    expires_in: int = Query(3600, ge=60, le=86400, description="Seconds until the URL expires"),
) -> SignedUrlResponse:
    # Requiring `path` to be one of this session's own snapshot_urls (rather
    # than trusting any string) stops an admin session from being used to
    # mint a signed URL for an arbitrary object elsewhere in the bucket.
    session = db.get(TestBSession, application_id)
    if session is None or not session.snapshot_urls or path not in session.snapshot_urls:
        raise HTTPException(
            status_code=404, detail="No such proctoring snapshot for this application"
        )

    url = create_snapshot_signed_url(path, expires_in)
    return _signed_url_response(url, expires_in)
