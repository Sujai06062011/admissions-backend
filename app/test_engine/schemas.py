import uuid
from datetime import datetime

from pydantic import BaseModel

# Deliberately not reusing TestASessionStart/TestASessionSubmit from
# app/schemas/stage3.py: that Start schema expects the CLIENT to supply
# generated_questions (wrong — the server must generate the question set, or
# a candidate could hand-pick their own), and that Submit schema lets the
# CLIENT supply submitted_at (wrong — the whole point of the expiry check is
# that the server's own clock decides when a submission happened; trusting a
# client-supplied timestamp would let anyone dodge the time limit by lying
# about it). Both existing schemas are left untouched, just not used here.


class TestAQuestionOut(BaseModel):
    """Candidate-facing question shape. Never includes the correct answer."""

    question_id: uuid.UUID
    question_text: str
    options: list[str]


class TestASessionStartResponse(BaseModel):
    application_id: uuid.UUID
    questions: list[TestAQuestionOut]
    duration_minutes: int
    started_at: datetime
    expires_at: datetime


class TestASessionSubmitRequest(BaseModel):
    answers: dict[str, int]  # question_id (str) -> selected option index


class TestASessionSubmitResponse(BaseModel):
    application_id: uuid.UUID
    score: float
    submitted_at: datetime
