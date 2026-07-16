import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.credentials.generation import generate_credentials, verify_password
from app.credentials.schemas import CredentialGenerateResponse, LoginRequest, LoginResponse
from app.db.session import get_db
from app.models.stage1 import Application
from app.models.stage3_test_a import Credential

router = APIRouter(tags=["credentials"])


@router.post(
    "/applications/{application_id}/credentials",
    response_model=CredentialGenerateResponse,
    status_code=201,
)
def create_credentials(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> CredentialGenerateResponse:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    credential, plaintext_password = generate_credentials(db, application)
    db.commit()
    db.refresh(credential)

    return CredentialGenerateResponse(
        application_id=credential.application_id,
        temp_username=credential.temp_username,
        temp_password=plaintext_password,
        expires_at=credential.expires_at,
        login_status=credential.login_status,
        created_at=credential.created_at,
    )


@router.post("/credentials/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    credential = (
        db.query(Credential).filter(Credential.temp_username == payload.temp_username).first()
    )
    if credential is None or not verify_password(
        payload.temp_password, credential.temp_password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if credential.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Credentials have expired")

    credential.login_status = "logged_in"
    db.commit()

    return LoginResponse(
        application_id=credential.application_id, login_status=credential.login_status
    )
