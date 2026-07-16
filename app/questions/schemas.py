import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionCategory = Literal[
    "quant", "verbal", "logical_reasoning", "english_grammar", "reading_comp"
]


# --- Question Bank ---


class QuestionBankCreate(BaseModel):
    name: str


class QuestionBankUpdate(BaseModel):
    name: str


class QuestionBankResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    name: str


# --- Question ---


class QuestionCreate(BaseModel):
    category: QuestionCategory
    question_text: str
    options: list[str] | None = None
    correct_answer: str | None = None
    difficulty: str = "medium"


class QuestionUpdate(BaseModel):
    category: QuestionCategory | None = None
    question_text: str | None = None
    options: list[str] | None = None
    correct_answer: str | None = None
    difficulty: str | None = None


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bank_id: uuid.UUID
    category: QuestionCategory
    question_text: str
    options: list[str] | None
    correct_answer: str | None
    difficulty: str | None
    created_at: datetime | None


# --- Test Blueprint ---


class TestBlueprintCreate(BaseModel):
    category: QuestionCategory
    question_count: int = Field(gt=0)
    duration_minutes: int = Field(gt=0)
    pass_threshold: float | None = None


class TestBlueprintUpdate(BaseModel):
    category: QuestionCategory | None = None
    question_count: int | None = Field(default=None, gt=0)
    duration_minutes: int | None = Field(default=None, gt=0)
    pass_threshold: float | None = None


class TestBlueprintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    category: QuestionCategory
    question_count: int
    duration_minutes: int
    pass_threshold: float | None


# --- Bulk CSV upload ---


class BulkUploadError(BaseModel):
    row: int
    reason: str


class BulkUploadResult(BaseModel):
    created_count: int
    questions: list[QuestionResponse]
    errors: list[BulkUploadError]
