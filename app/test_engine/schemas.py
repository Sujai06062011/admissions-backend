import uuid
from datetime import datetime
from typing import Literal

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
    """Candidate-facing question shape. Never includes the correct answer(s).

    answer_type tells the client whether to render this question as
    single-select (radio buttons) or multi-select ("select all that
    apply" — checkboxes).
    """

    question_id: uuid.UUID
    question_text: str
    options: list[str]
    answer_type: Literal["single", "multi"]


class TestASessionStartResponse(BaseModel):
    application_id: uuid.UUID
    questions: list[TestAQuestionOut]
    duration_minutes: int
    started_at: datetime
    expires_at: datetime


class TestASessionSubmitRequest(BaseModel):
    # question_id (str) -> selected option index(es). Always a list, even
    # for a single-select question (one-element list) — a uniform shape
    # means grading never needs to special-case answer_type.
    answers: dict[str, list[int]]


class TestASessionSubmitResponse(BaseModel):
    application_id: uuid.UUID
    score: float
    submitted_at: datetime
