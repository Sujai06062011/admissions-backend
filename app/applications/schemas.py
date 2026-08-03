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


class CandidateGdStatus(BaseModel):
    """Group Discussion card on /campus/portal. Topic is null until host Start."""

    assigned: bool = False
    session_id: uuid.UUID | None = None
    track: str | None = None  # online | manual
    label: str | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = None
    status: str | None = None
    join_opens_at: datetime | None = None
    join_opens_minutes_before: int | None = None
    join_enabled: bool = False
    started_at: datetime | None = None
    ends_at: datetime | None = None
    ended_at: datetime | None = None
    topic: str | None = None
    completed: bool = False


class CandidateStatusResponse(BaseModel):
    application_id: uuid.UUID
    program_id: uuid.UUID
    status: ApplicationStatus
    campus_session_assigned: bool
    applicant_name: str | None = None
    application_number: str | None = None
    test_a: CandidateTestAStatus
    test_b: CandidateTestBStatus
    group_discussion: CandidateGdStatus | None = None
