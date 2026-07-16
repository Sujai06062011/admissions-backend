import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DeliveryChannel = Literal["email", "whatsapp"]
PromptType = Literal["image", "video", "question"]


# --- Credentials ---


class CredentialCreate(BaseModel):
    application_id: uuid.UUID
    temp_username: str
    temp_password_hash: str
    expires_at: datetime
    delivered_via: list[DeliveryChannel] = Field(default_factory=list)


class CredentialResponse(BaseModel):
    """Excludes temp_password_hash — never returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    application_id: uuid.UUID
    temp_username: str
    expires_at: datetime
    delivered_via: list[DeliveryChannel] | None
    login_status: str | None
    created_at: datetime | None


# --- Test A sessions (question-bank based test) ---


class TestASessionStart(BaseModel):
    generated_questions: list[Any]
    started_at: datetime | None = None


class TestASessionSubmit(BaseModel):
    answers: dict[str, Any]
    submitted_at: datetime | None = None


class TestASessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: uuid.UUID
    generated_questions: list[Any]
    answers: dict[str, Any] | None
    score: float | None
    started_at: datetime | None
    submitted_at: datetime | None


# --- Test B sessions (AI video interview) ---


class RubricScore(BaseModel):
    grammar: float | None = None
    fluency: float | None = None
    reasoning: float | None = None
    coherence: float | None = None


class TestBSessionCreate(BaseModel):
    application_id: uuid.UUID
    prompt_id: uuid.UUID | None = None
    recording_url: str | None = None
    recorded_at: datetime | None = None


class TestBSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: uuid.UUID
    prompt_id: uuid.UUID | None
    recording_url: str | None
    transcript: str | None
    rubric_score: RubricScore | None
    rationale: str | None
    recorded_at: datetime | None
