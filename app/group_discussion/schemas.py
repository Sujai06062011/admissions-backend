import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AssignmentStrategy = Literal["composite", "gender_mix", "random", "manual"]


class SmokeCreateMeetingRequest(BaseModel):
    subject: str = Field(default="Admit GD smoke test", max_length=200)
    start: datetime | None = None
    duration_minutes: int = Field(default=60, ge=15, le=240)


class SmokeCreateMeetingResponse(BaseModel):
    meeting_id: str
    join_url: str
    subject: str
    start_date_time: str
    end_date_time: str
    organizer_upn: str


class CreateGdSessionRequest(BaseModel):
    program_id: uuid.UUID
    label: str | None = Field(default=None, max_length=120)
    target_size: int = Field(default=5, ge=2, le=12)
    scheduled_at: datetime | None = None
    duration_minutes: int = Field(default=60, ge=15, le=240)
    assignment_strategy: AssignmentStrategy = "composite"
    application_ids: list[uuid.UUID] | None = None
    professor_email: str | None = None
    auto_assign: bool = True


class AssignGdSessionRequest(BaseModel):
    assignment_strategy: AssignmentStrategy | None = None
    application_ids: list[uuid.UUID] | None = None
    target_size: int | None = Field(default=None, ge=2, le=12)


class GdParticipantResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    applicant_name: str | None = None
    applicant_email: str | None = None
    application_number: str | None = None
    composite_score: float | None = None
    gender: str | None = None
    role: str
    invite_status: str | None = None
    invite_sent_at: datetime | None = None
    scores: dict | None = None
    overall_score: float | None = None
    score_rationale: str | None = None
    speaker_labels: list[str] | None = None
    scoring_status: str | None = None
    scored_at: datetime | None = None


class GdSessionResponse(BaseModel):
    id: uuid.UUID
    program_id: uuid.UUID
    label: str | None
    target_size: int
    scheduled_at: datetime | None
    duration_minutes: int
    assignment_strategy: str
    status: str
    teams_meeting_id: str | None
    join_url: str | None
    professor_email: str | None
    recording_storage_path: str | None = None
    transcript_text: str | None = None
    artifacts_status: str | None = None
    artifacts_error: str | None = None
    artifacts_fetched_at: datetime | None = None
    created_at: datetime | None
    participants: list[GdParticipantResponse]


class EligibleCandidateResponse(BaseModel):
    application_id: uuid.UUID
    applicant_name: str | None
    applicant_email: str | None
    application_number: str | None
    composite_score: float | None
    gender: str | None
    test_a_score: float | None
    test_b_score: float | None


class SendInvitesResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    results: list[dict]


class UploadTranscriptRequest(BaseModel):
    """Manual transcript ingest when Graph transcript API is tenant-blocked.

    Paste plain text, or WebVTT downloaded from Stream's Transcript → Download.
    """

    transcript: str = Field(min_length=1, max_length=500_000)
    is_vtt: bool = False

