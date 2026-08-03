"""Pull Teams recording + transcript into Supabase / DB after a GD ends."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.group_discussion.storage import save_gd_recording
from app.group_discussion.teams_graph import (
    TeamsGraphApiError,
    fetch_latest_recording,
    fetch_latest_transcript,
)
from app.models.group_discussion import GdSession


def ingest_session_artifacts(db: Session, session: GdSession) -> GdSession:
    """Fetch Graph recording + transcript for session.teams_meeting_id.

    Safe to re-run: overwrites prior artifact fields when new content is found.
    Does not change Application.status.
    """
    if not session.teams_meeting_id:
        raise ValueError("Session has no teams_meeting_id")

    session.artifacts_status = "processing"
    session.artifacts_error = None
    session.updated_at = datetime.now(timezone.utc)
    db.flush()

    errors: list[str] = []
    recording = None
    transcript = None

    # Fetch independently — tenant may allow recordings but block Graph transcripts.
    try:
        recording = fetch_latest_recording(session.teams_meeting_id)
    except TeamsGraphApiError as exc:
        errors.append(f"recording Graph {exc.status_code}: {exc.body[:300]}")

    try:
        transcript = fetch_latest_transcript(session.teams_meeting_id)
    except TeamsGraphApiError as exc:
        errors.append(f"transcript Graph {exc.status_code}: {exc.body[:300]}")

    if recording is None and transcript is None:
        if errors:
            session.artifacts_status = "failed"
            session.artifacts_error = " | ".join(errors)[:800]
        else:
            session.artifacts_status = "pending"
            session.artifacts_error = (
                "No recording or transcript available yet. "
                "Wait a few minutes after the meeting ends, ensure recording completed, then retry."
            )
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        return session

    if recording is not None:
        suffix = ".mp4"
        if "webm" in (recording.content_type or ""):
            suffix = ".webm"
        path = save_gd_recording(
            session.id,
            recording.content_bytes,
            content_type=recording.content_type,
            suffix=suffix,
        )
        session.recording_storage_path = path
        session.recording_graph_id = recording.recording_id

    if transcript is not None:
        session.transcript_text = transcript.plain_text or transcript.vtt_text
        session.transcript_vtt = transcript.vtt_text
        session.transcript_graph_id = transcript.transcript_id

    # Partial success is OK (e.g. video in Supabase while transcript API is tenant-blocked).
    session.artifacts_status = "ready"
    session.artifacts_error = " | ".join(errors)[:800] if errors else None
    session.artifacts_fetched_at = datetime.now(timezone.utc)
    session.status = "completed"
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session
