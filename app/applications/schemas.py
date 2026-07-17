import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.stage1 import (
    ApplicantResponse,
    ApplicationResponse,
    ApplicationStatus,
    ProfileDataResponse,
    UploadedDocumentResponse,
)


class ApplicationProfileResponse(BaseModel):
    application: ApplicationResponse
    applicant: ApplicantResponse
    profile_data: ProfileDataResponse | None
    documents: list[UploadedDocumentResponse]


# --- Candidate-facing status (drives the /campus portal's routing) ---


class CandidateTestAStatus(BaseModel):
    submitted: bool
    score: float | None
    in_progress: bool
    expires_at: datetime | None


class CandidateTestBStatus(BaseModel):
    submitted: bool
    recorded_at: datetime | None


class CandidateStatusResponse(BaseModel):
    application_id: uuid.UUID
    program_id: uuid.UUID
    status: ApplicationStatus
    campus_session_assigned: bool
    test_a: CandidateTestAStatus
    test_b: CandidateTestBStatus
