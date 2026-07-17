from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.jwt import InvalidToken, decode_access_token
from app.db.session import get_db
from app.models.core import AdminUser

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    """FastAPI dependency for protected admin routes: validates the session
    token on the Authorization header and returns the current AdminUser.

    Reloads the admin from the database on every call rather than trusting
    the token's claims wholesale, so a deleted admin's still-unexpired token
    stops working immediately instead of at next login.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        admin_id, _tenant_id, _role = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    admin = db.get(AdminUser, admin_id)
    if admin is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return admin
