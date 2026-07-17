import logging
import uuid

from fastapi import BackgroundTasks

from app.db.session import SessionLocal
from app.interview_engine.scoring import score_transcript
from app.interview_engine.storage import download_recording
from app.interview_engine.transcription import transcribe_audio
from app.models.stage3_test_b import TestBSession
from app.preferences.matching import compute_preference_match

logger = logging.getLogger(__name__)


def process_interview_recording(application_id: str) -> None:
    """Transcribes and scores a just-uploaded interview recording, then writes
    transcript/rubric_score/rationale onto the TestBSession row.

    Runs as a background task with its own DB session — the request's session
    is already gone by the time this executes, so it can't reuse one. Catches
    broadly and just logs on failure rather than raising, since there's no
    request left to surface an error to; the row simply keeps
    transcript/rubric_score/rationale as null until someone investigates.
    """
    db = SessionLocal()
    try:
        session = db.get(TestBSession, uuid.UUID(application_id))
        if session is None or not session.recording_url:
            logger.error(
                "No TestBSession/recording found for application_id=%s", application_id
            )
            return

        filename = session.recording_url.rsplit("/", 1)[-1]
        audio_bytes = download_recording(session.recording_url)
        transcript = transcribe_audio(filename, audio_bytes)

        rubric_score, rationale = score_transcript(session.prompt, transcript)

        session.transcript = transcript
        session.rubric_score = rubric_score
        session.rationale = rationale
        db.flush()

        # Re-score against PreferenceConfig now that test_b_score is
        # available — completes the composite score's final stage.
        compute_preference_match(db, session.application)

        db.commit()
        logger.info("Interview scoring complete for application_id=%s", application_id)
    except Exception:
        logger.exception("Interview scoring failed for application_id=%s", application_id)
    finally:
        db.close()


def enqueue_interview_scoring(background_tasks: BackgroundTasks, application_id: str) -> None:
    """Schedules the transcription+scoring job.

    Routed through FastAPI's BackgroundTasks for now — same pattern as
    workers/ocr_jobs.py — so the upload endpoint returns immediately. Swap
    this function's body for a real queue (Celery/RQ) later without touching
    callers.
    """
    background_tasks.add_task(process_interview_recording, application_id)
