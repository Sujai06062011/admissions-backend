import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.models.core import AdminUser

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRY = timedelta(hours=12)


class InvalidToken(Exception):
    """Raised for any token that isn't a currently-valid admin session —
    expired, malformed, wrong signature, or missing required claims. Callers
    treat all of these identically (401), so this doesn't distinguish which.
    """


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(admin: AdminUser) -> tuple[str, datetime]:
    """Issues a signed session token for an admin. Returns (token, expires_at)."""
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_EXPIRY
    payload = {
        "sub": str(admin.id),
        "tenant_id": str(admin.tenant_id),
        "role": admin.role,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _secret(), algorithm=ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Verifies a session token's signature and expiry, and returns
    (admin_id, tenant_id, role) from its claims.

    Raises InvalidToken for anything that isn't a currently-valid session —
    the caller (the FastAPI dependency) is responsible for turning that into
    a 401, not this function.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["tenant_id"]), payload["role"]
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidToken from exc
