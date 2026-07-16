import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.stage3 import PromptType


class PromptBankCreate(BaseModel):
    name: str


class PromptBankUpdate(BaseModel):
    name: str


class PromptBankResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    name: str


class PromptCreate(BaseModel):
    prompt_type: PromptType
    media_url: str | None = None
    prompt_text: str | None = None
    category: str | None = None


class PromptUpdate(BaseModel):
    prompt_type: PromptType | None = None
    media_url: str | None = None
    prompt_text: str | None = None
    category: str | None = None


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bank_id: uuid.UUID
    prompt_type: PromptType
    media_url: str | None
    prompt_text: str | None
    category: str | None
    created_at: datetime | None
