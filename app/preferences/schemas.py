import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.stage1 import ApplicationResponse
from app.schemas.stage2 import PreferenceMatchResultResponse


class PreferenceConfigCreate(BaseModel):
    field_name: str
    is_hard_cutoff: bool = False
    cutoff_value: float | None = None
    soft_weight: float = 0


class PreferenceConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    field_name: str
    is_hard_cutoff: bool | None
    cutoff_value: float | None
    soft_weight: float | None
    created_at: datetime | None


class ApplicationMatchResultItem(BaseModel):
    application: ApplicationResponse
    match_result: PreferenceMatchResultResponse | None
