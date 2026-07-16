from pydantic import BaseModel

from app.schemas.stage1 import (
    ApplicantResponse,
    ApplicationResponse,
    ProfileDataResponse,
    UploadedDocumentResponse,
)


class ApplicationProfileResponse(BaseModel):
    application: ApplicationResponse
    applicant: ApplicantResponse
    profile_data: ProfileDataResponse | None
    documents: list[UploadedDocumentResponse]
