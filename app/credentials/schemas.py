import uuid
from datetime import datetime

from pydantic import BaseModel


class CredentialGenerateResponse(BaseModel):
    """Returned only at generation time — temp_password is shown once, plaintext,
    and is never persisted or retrievable again after this response."""

    application_id: uuid.UUID
    temp_username: str
    temp_password: str
    expires_at: datetime
    login_status: str | None
    created_at: datetime | None


class LoginRequest(BaseModel):
    temp_username: str
    temp_password: str


class LoginResponse(BaseModel):
    application_id: uuid.UUID
    login_status: str | None
