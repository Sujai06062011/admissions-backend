import uuid
from datetime import datetime

from pydantic import BaseModel


class CallForInterviewRequest(BaseModel):
    application_ids: list[uuid.UUID]


class CallForInterviewResult(BaseModel):
    application_id: uuid.UUID
    success: bool
    detail: str | None = None


class CallForInterviewResponse(BaseModel):
    results: list[CallForInterviewResult]


class ScheduleInterviewRequest(BaseModel):
    scheduled_at: datetime


class InterviewResponse(BaseModel):
    application_id: uuid.UUID
    scheduled_at: datetime | None
    status: str | None
