import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.applications.numbering import build_application_number
from app.applications.schemas import (
    ApplicationProfileResponse,
    CandidateStatusResponse,
    CandidateTestAStatus,
    CandidateTestBStatus,
)
from app.applications.storage import save_upload
from app.db.session import get_db
from app.models.core import Program, Tenant
from app.models.stage1 import Applicant, Application, ProfileData, UploadedDocument
from app.preferences.matching import compute_preference_match
from app.schemas.stage1 import (
    ApplicantResponse,
    ApplicantUpdate,
    ApplicationResponse,
    ApplicationSubmissionRequest,
    ApplicationSubmissionResponse,
    DocType,
    ProfileDataResponse,
    ProfileDataUpdate,
    UploadedDocumentResponse,
)
from app.test_engine.router import _is_expired, _total_duration_minutes
from workers.ocr_jobs import enqueue_ocr_job

router = APIRouter(prefix="/applications", tags=["applications"])

# Every other doc_type is a single fixed slot in the candidate form (one
# address proof, one 10th marksheet, etc.) — uploading again should replace
# it, not accumulate a second row that then shows up as a duplicate section
# on the review/confirm screens.
_REPEATABLE_DOC_TYPES = {"certifications", "experience_certificate"}

# Keep aligned with DocumentUploadCard's ACCEPTED_TYPES on the frontend.
# Vision OCR handles PDF via files:annotate and JPEG/PNG/WebP via images:annotate.
_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


@router.post("", response_model=ApplicationSubmissionResponse, status_code=201)
def create_application(
    payload: ApplicationSubmissionRequest, db: Session = Depends(get_db)
) -> ApplicationSubmissionResponse:
    if db.get(Tenant, payload.tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Locks the program row so concurrent signups for the same program are
    # serialized here, giving each one a distinct, gap-tolerant sequence
    # number instead of racing on a MAX() read.
    program = (
        db.query(Program)
        .filter(Program.id == payload.program_id)
        .with_for_update()
        .first()
    )
    if program is None or program.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Program not found for tenant")

    next_sequence_number = (
        db.query(func.coalesce(func.max(Application.sequence_number), 0))
        .filter(Application.program_id == payload.program_id)
        .scalar()
    ) + 1

    applicant = Applicant(**payload.applicant.model_dump())
    db.add(applicant)
    db.flush()

    application_number = build_application_number(
        applicant.full_name, payload.profile.data.get("dob"), next_sequence_number
    )

    application = Application(
        tenant_id=payload.tenant_id,
        program_id=payload.program_id,
        applicant_id=applicant.id,
        sequence_number=next_sequence_number,
        application_number=application_number,
    )
    db.add(application)
    db.flush()

    profile_data = ProfileData(
        application_id=application.id,
        data=payload.profile.data,
        form_template_version=payload.profile.form_template_version,
    )
    db.add(profile_data)

    db.commit()
    db.refresh(application)
    db.refresh(applicant)
    db.refresh(profile_data)

    return ApplicationSubmissionResponse(
        application=ApplicationResponse.model_validate(application),
        applicant=ApplicantResponse.model_validate(applicant),
        profile_data=ProfileDataResponse.model_validate(profile_data),
    )


@router.post(
    "/{application_id}/documents",
    response_model=UploadedDocumentResponse,
    status_code=201,
)
def upload_document(
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    doc_type: DocType = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadedDocument:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type — please upload a PDF or image (JPG, PNG, or WebP)",
        )

    if doc_type not in _REPEATABLE_DOC_TYPES:
        db.query(UploadedDocument).filter(
            UploadedDocument.application_id == application_id,
            UploadedDocument.doc_type == doc_type,
        ).delete()

    file_url = save_upload(application_id, file)

    document = UploadedDocument(
        application_id=application_id,
        doc_type=doc_type,
        file_url=file_url,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    enqueue_ocr_job(background_tasks, str(document.id))

    return document


@router.patch("/{application_id}/profile", response_model=ProfileDataResponse)
def update_application_profile(
    application_id: uuid.UUID, payload: ProfileDataUpdate, db: Session = Depends(get_db)
) -> ProfileDataResponse:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    profile_data = db.get(ProfileData, application_id)
    if profile_data is None:
        raise HTTPException(status_code=404, detail="Profile data not found")

    profile_data.data = payload.data
    db.flush()

    # Score against the program's PreferenceConfig immediately so hard-pass /
    # composite_score are available as soon as the candidate confirms &
    # submits, rather than only after an admin manually calls compute-match.
    compute_preference_match(db, application)

    db.commit()
    db.refresh(profile_data)

    return ProfileDataResponse.model_validate(profile_data)


@router.patch("/{application_id}/applicant", response_model=ApplicantResponse)
def update_applicant(
    application_id: uuid.UUID, payload: ApplicantUpdate, db: Session = Depends(get_db)
) -> ApplicantResponse:
    """Lets the candidate app fix a typo'd name/phone/email from the Confirm &
    Submit screen — full_name/phone/email live on Applicant, not the
    profile_data JSON blob that /profile above patches, so this needed its
    own endpoint. Only fields actually present in the request body are
    changed (exclude_unset), so this can be called with just one field.
    """
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    applicant = db.get(Applicant, application.applicant_id)
    if applicant is None:
        raise HTTPException(status_code=404, detail="Applicant not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(applicant, field, value)

    db.commit()
    db.refresh(applicant)

    return ApplicantResponse.model_validate(applicant)


@router.get("/{application_id}", response_model=ApplicationProfileResponse)
def get_application_profile(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> ApplicationProfileResponse:
    application = (
        db.query(Application)
        .options(
            selectinload(Application.applicant),
            selectinload(Application.profile_data),
            selectinload(Application.uploaded_documents),
        )
        .filter(Application.id == application_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    return ApplicationProfileResponse(
        application=ApplicationResponse.model_validate(application),
        applicant=ApplicantResponse.model_validate(application.applicant),
        profile_data=(
            ProfileDataResponse.model_validate(application.profile_data)
            if application.profile_data
            else None
        ),
        documents=[
            UploadedDocumentResponse.model_validate(doc)
            for doc in application.uploaded_documents
        ],
    )


@router.get("/{application_id}/candidate-status", response_model=CandidateStatusResponse)
def get_candidate_status(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> CandidateStatusResponse:
    """Coarse ApplicationStatus alone can't tell the /campus portal whether to
    route a candidate into Test A or Test B next — "moved_to_campus" covers
    both. This reads the actual TestASession/TestBSession/CampusSession rows
    so the portal can show real per-stage state without a side-effecting call
    (starting test-a-session/start again while one is already in progress
    raises a 409).
    """
    application = (
        db.query(Application)
        .options(
            selectinload(Application.applicant),
            selectinload(Application.test_a_session),
            selectinload(Application.test_b_session),
            selectinload(Application.campus_session),
        )
        .filter(Application.id == application_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    test_a_session = application.test_a_session
    test_a_in_progress = False
    test_a_expires_at = None
    if test_a_session is not None and test_a_session.submitted_at is None:
        duration_minutes = _total_duration_minutes(db, application.program_id)
        if duration_minutes:
            test_a_expires_at = test_a_session.started_at + timedelta(minutes=duration_minutes)
            test_a_in_progress = not _is_expired(test_a_session, duration_minutes)

    test_b_session = application.test_b_session

    return CandidateStatusResponse(
        application_id=application.id,
        program_id=application.program_id,
        status=application.status,
        campus_session_assigned=application.campus_session is not None,
        applicant_name=application.applicant.full_name if application.applicant else None,
        application_number=application.application_number,
        test_a=CandidateTestAStatus(
            submitted=test_a_session is not None and test_a_session.submitted_at is not None,
            score=test_a_session.score if test_a_session else None,
            in_progress=test_a_in_progress,
            expires_at=test_a_expires_at,
        ),
        test_b=CandidateTestBStatus(
            submitted=test_b_session is not None and test_b_session.recorded_at is not None,
            recorded_at=test_b_session.recorded_at if test_b_session else None,
        ),
    )
