import uuid
from datetime import datetime

from pydantic import BaseModel

from app.campus.schemas import CampusSessionResponse
from app.schemas.stage1 import ApplicantResponse, ApplicationResponse, ProfileDataResponse, UploadedDocumentResponse
from app.schemas.stage2 import AdminDecisionResponse, PreferenceMatchResultResponse
from app.schemas.stage3 import TestASessionResponse, TestBSessionResponse


class FunnelResponse(BaseModel):
    program_id: uuid.UUID
    received: int
    rejected_on_preference_match: int
    moved_to_campus: int
    test_a_complete: int
    test_b_complete: int
    called_for_interview: int
    offered: int


class CandidateListItem(BaseModel):
    application_id: uuid.UUID
    applicant_name: str | None
    program_id: uuid.UUID
    status: str
    preference_match_score: float | None
    test_a_score: float | None
    test_b_score: float | None
    # None = no proctoring review yet (no Test B recording, or snapshots not
    # reviewed yet); the main applications table only needs to know "flag it
    # or don't" without loading the full review notes/snapshots, which the
    # candidate drawer fetches separately in more detail.
    proctoring_flagged: bool | None = None


class CandidateProfileResponse(BaseModel):
    application: ApplicationResponse
    applicant: ApplicantResponse
    profile_data: ProfileDataResponse | None
    documents: list[UploadedDocumentResponse]
    preference_match: PreferenceMatchResultResponse | None
    admin_decisions: list[AdminDecisionResponse]
    campus_session: CampusSessionResponse | None
    test_a_session: TestASessionResponse | None
    test_b_session: TestBSessionResponse | None


class SignedUrlResponse(BaseModel):
    url: str
    expires_at: datetime
