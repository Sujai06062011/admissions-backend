import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ApplicationStatus = Literal[
    "submitted",
    "under_review",
    "moved_to_campus",
    "testing_complete",
    "called_for_interview",
    "offered",
    "rejected",
]

DocType = Literal[
    "resume",
    "10th_marksheet",
    "12th_marksheet",
    "ug_marksheet",
    "pg_marksheet",
    "certifications",
    "address_proof",
    "id_proof",
    "experience_certificate",
]


# --- Applicant ---


class ApplicantCreate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None


class ApplicantUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None


class ApplicantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str | None
    email: str | None
    phone: str | None
    created_at: datetime | None


# --- Profile data ---


class ProfileDataSubmit(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    form_template_version: str | None = None


class ProfileDataUpdate(BaseModel):
    data: dict[str, Any]


class ProfileDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: uuid.UUID
    data: dict[str, Any]
    form_template_version: str | None
    updated_at: datetime | None


# --- Application submission (Stage 1 entry point) ---


class ApplicationSubmissionRequest(BaseModel):
    tenant_id: uuid.UUID
    program_id: uuid.UUID
    applicant: ApplicantCreate
    profile: ProfileDataSubmit


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    program_id: uuid.UUID
    applicant_id: uuid.UUID
    status: ApplicationStatus
    sequence_number: int
    application_number: str
    created_at: datetime | None
    updated_at: datetime | None


class ApplicationSubmissionResponse(BaseModel):
    application: ApplicationResponse
    applicant: ApplicantResponse
    profile_data: ProfileDataResponse


# --- Uploaded documents ---


class UploadedDocumentCreate(BaseModel):
    doc_type: DocType
    file_url: str


class UploadedDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    doc_type: DocType
    file_url: str
    ocr_result: dict[str, Any] | None
    ocr_confidence: float | None
    created_at: datetime | None
