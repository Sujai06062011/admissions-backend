import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CampusScheduleCreate(BaseModel):
    session_date: date
    capacity: int = Field(gt=0)


class CampusScheduleUpdate(BaseModel):
    session_date: date | None = None
    capacity: int | None = Field(default=None, gt=0)


class CampusScheduleResponse(BaseModel):
    id: uuid.UUID
    program_id: uuid.UUID
    session_date: date
    capacity: int
    booked_count: int


class CampusSessionResponse(BaseModel):
    application_id: uuid.UUID
    schedule_id: uuid.UUID
    session_date: date
    slot_time: datetime | None
    check_in_status: str | None
    device_id: str | None


class CheckInRequest(BaseModel):
    device_id: str | None = None
