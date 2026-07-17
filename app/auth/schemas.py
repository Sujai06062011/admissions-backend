import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str | None
    role: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    admin: AdminProfileResponse
