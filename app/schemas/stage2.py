import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

DecisionStage = Literal["stage2_move_to_campus", "stage3_call_for_interview"]
DecisionOutcome = Literal["approved", "rejected", "manual_override"]


# --- Preference match results ---


class MatchReason(BaseModel):
    field: str
    expected: float | str | None = None
    actual: float | str | None = None
    passed: bool


class PreferenceMatchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: uuid.UUID
    composite_score: float | None
    hard_pass: bool | None
    reasons: list[MatchReason]
    computed_at: datetime | None


# --- Admin decisions ---


class AdminDecisionCreate(BaseModel):
    application_id: uuid.UUID
    stage: DecisionStage
    decision: DecisionOutcome
    notes: str | None = None


class AdminDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    stage: DecisionStage
    decision: DecisionOutcome
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    notes: str | None
