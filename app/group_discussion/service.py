"""Shared helpers for GD session responses — no status transitions on Application."""

from __future__ import annotations

from app.group_discussion.schemas import GdParticipantResponse, GdSessionResponse
from app.models.group_discussion import GdSession
from app.models.stage1 import Application


def _gender_from_app(app: Application | None) -> str | None:
    if app is None or app.profile_data is None or not isinstance(app.profile_data.data, dict):
        return None
    raw = app.profile_data.data.get("gender")
    return raw if isinstance(raw, str) else None


def serialize_session(session: GdSession) -> GdSessionResponse:
    participants: list[GdParticipantResponse] = []
    for p in session.participants:
        app = p.application
        applicant = app.applicant if app else None
        match = app.preference_match_result if app else None
        participants.append(
            GdParticipantResponse(
                id=p.id,
                application_id=p.application_id,
                applicant_name=applicant.full_name if applicant else None,
                applicant_email=applicant.email if applicant else None,
                application_number=app.application_number if app else None,
                composite_score=float(match.composite_score)
                if match and match.composite_score is not None
                else None,
                gender=_gender_from_app(app),
                role=p.role,
                invite_status=p.invite_status,
                invite_sent_at=p.invite_sent_at,
            )
        )
    return GdSessionResponse(
        id=session.id,
        program_id=session.program_id,
        label=session.label,
        target_size=session.target_size,
        scheduled_at=session.scheduled_at,
        duration_minutes=session.duration_minutes,
        assignment_strategy=session.assignment_strategy,
        status=session.status,
        teams_meeting_id=session.teams_meeting_id,
        join_url=session.join_url,
        professor_email=session.professor_email,
        recording_storage_path=session.recording_storage_path,
        transcript_text=session.transcript_text,
        artifacts_status=session.artifacts_status,
        artifacts_error=session.artifacts_error,
        artifacts_fetched_at=session.artifacts_fetched_at,
        created_at=session.created_at,
        participants=participants,
    )
