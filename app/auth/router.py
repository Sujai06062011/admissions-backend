from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_admin
from app.auth.jwt import create_access_token
from app.auth.schemas import AdminLoginRequest, AdminLoginResponse, AdminProfileResponse
from app.credentials.generation import verify_password
from app.db.session import get_db
from app.models.core import AdminUser

router = APIRouter(prefix="/admin", tags=["admin_auth"])


@router.post("/login", response_model=AdminLoginResponse)
def login(payload: AdminLoginRequest, db: Session = Depends(get_db)) -> AdminLoginResponse:
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).first()

    # Same generic message whether the email doesn't exist, has no password
    # set yet, or the password is wrong — distinguishing any of these in the
    # response would let a caller enumerate valid admin emails.
    if admin is None or admin.password_hash is None or not verify_password(
        payload.password, admin.password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token, expires_at = create_access_token(admin)

    return AdminLoginResponse(
        access_token=token,
        expires_at=expires_at,
        admin=AdminProfileResponse.model_validate(admin),
    )


@router.get("/me", response_model=AdminProfileResponse)
def get_me(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    return admin
