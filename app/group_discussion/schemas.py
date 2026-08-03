import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AssignmentStrategy = Literal["composite", "gender_mix", "random", "manual"]
GdTrack = Literal["online", "manual"]
JoinRole = Literal["candidate", "host"]


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


class SmokeAcsTokenResponse(BaseModel):
    user_id: str
    token: str
    expires_on: datetime


class CreateGdSessionRequest(BaseModel):
    program_id: uuid.UUID
    label: str | None = Field(default=None, max_length=120)
    target_size: int = Field(default=5, ge=5, le=7)
    scheduled_at: datetime | None = None
    duration_minutes: int = Field(default=60, ge=15, le=240)
    assignment_strategy: AssignmentStrategy = "composite"
    application_ids: list[uuid.UUID] | None = None
    professor_email: str | None = None
    professor_name: str | None = Field(default=None, max_length=120)
    topic: str | None = Field(default=None, max_length=500)
    track: GdTrack = "online"
    join_opens_minutes_before: int | None = Field(default=None, ge=0, le=120)
    auto_assign: bool = True


class AssignGdSessionRequest(BaseModel):
    assignment_strategy: AssignmentStrategy | None = None
    application_ids: list[uuid.UUID] | None = None
    target_size: int | None = Field(default=None, ge=5, le=7)


class UpdateGdSessionRequest(BaseModel):
    """Configure moderator / topic / schedule before send or start."""

    label: str | None = Field(default=None, max_length=120)
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=240)
    professor_email: str | None = None
    professor_name: str | None = Field(default=None, max_length=120)
    topic: str | None = Field(default=None, max_length=500)
    join_opens_minutes_before: int | None = Field(default=None, ge=0, le=120)
    track: GdTrack | None = None


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
    track: str = "online"
    teams_meeting_id: str | None
    join_url: str | None
    topic: str | None = None
    professor_email: str | None
    professor_name: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    join_opens_minutes_before: int | None = None
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


class AdminAcsJoinRequest(BaseModel):
    """Mint ACS credentials for an existing GD session (admin / host testing)."""

    role: JoinRole = "host"
    display_name: str = Field(default="GD Host", max_length=80)
    # Host/admin testing before the candidate join window opens.
    bypass_join_window: bool = True


class CandidateAcsJoinRequest(BaseModel):
    application_id: uuid.UUID
    display_name: str | None = Field(default=None, max_length=80)


class AcsJoinResponse(BaseModel):
    session_id: uuid.UUID
    role: JoinRole
    display_name: str
    acs_user_id: str
    acs_token: str
    acs_token_expires_on: datetime
    teams_meeting_id: str | None
    # Returned for SDK join only — never put in candidate emails.
    teams_join_url: str
    status: str
    scheduled_at: datetime | None
    join_opens_at: datetime | None
    started_at: datetime | None
    ends_at: datetime | None = None
    # Null until host Start (topic gating).
    topic: str | None = None
    duration_minutes: int


class StartGdSessionResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    started_at: datetime
    ends_at: datetime
    topic: str | None


class EndGdSessionResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    ended_at: datetime


class CandidateGdSessionStateResponse(BaseModel):
    """Pollable session state for the custom GD UI (topic appears after host Start)."""

    session_id: uuid.UUID
    status: str
    scheduled_at: datetime | None
    join_opens_at: datetime | None
    join_enabled: bool
    started_at: datetime | None
    ends_at: datetime | None
    ended_at: datetime | None
    topic: str | None
    duration_minutes: int
    track: str
