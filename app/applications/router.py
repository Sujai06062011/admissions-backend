import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload

from app.applications.schemas import ApplicationProfileResponse
from app.applications.storage import save_upload
from app.db.session import get_db
from app.models.core import Program, Tenant
from app.models.stage1 import Applicant, Application, ProfileData, UploadedDocument
from app.schemas.stage1 import (
    ApplicantResponse,
    ApplicationResponse,
    ApplicationSubmissionRequest,
    ApplicationSubmissionResponse,
    DocType,
    ProfileDataResponse,
    UploadedDocumentResponse,
)
from workers.ocr_jobs import enqueue_ocr_job

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationSubmissionResponse, status_code=201)
def create_application(
    payload: ApplicationSubmissionRequest, db: Session = Depends(get_db)
) -> ApplicationSubmissionResponse:
    if db.get(Tenant, payload.tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    program = db.get(Program, payload.program_id)
    if program is None or program.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Program not found for tenant")

    applicant = Applicant(**payload.applicant.model_dump())
    db.add(applicant)
    db.flush()

    application = Application(
        tenant_id=payload.tenant_id,
        program_id=payload.program_id,
        applicant_id=applicant.id,
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
