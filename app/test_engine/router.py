import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.stage1 import Application
from app.models.stage3_test_a import TestASession, TestBlueprint
from app.preferences.matching import compute_preference_match
from app.test_engine.generation import (
    InsufficientQuestions,
    MalformedQuestion,
    NoTestBlueprintConfigured,
    build_generated_questions,
)
from app.test_engine.grading import grade_submission
from app.test_engine.schemas import (
    TestAQuestionOut,
    TestASessionStartResponse,
    TestASessionSubmitRequest,
    TestASessionSubmitResponse,
)

router = APIRouter(tags=["test_engine"])


def _total_duration_minutes(db: Session, program_id: uuid.UUID) -> int:
    """Not stored on TestASession — there's no column for it — so it's
    recomputed from the program's current TestBlueprint rows every time it's
    needed (at start, to check an existing session's expiry, and again at
    submit). Known limitation: if an admin edits blueprint durations while a
    session is in progress, that changes the effective deadline for anyone
    mid-test, since nothing freezes the value at start time.
    """
    blueprints = db.query(TestBlueprint).filter(TestBlueprint.program_id == program_id).all()
    return sum(b.duration_minutes for b in blueprints)


def _is_expired(session: TestASession, duration_minutes: int) -> bool:
    deadline = session.started_at + timedelta(minutes=duration_minutes)
    return datetime.now(timezone.utc) > deadline


@router.post(
    "/applications/{application_id}/test-a-session/start",
    response_model=TestASessionStartResponse,
    status_code=201,
)
def start_test_a_session(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> TestASessionStartResponse:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    existing = db.get(TestASession, application_id)
    if existing is not None:
        if existing.submitted_at is not None:
            raise HTTPException(
                status_code=409, detail="Test A has already been submitted for this application"
            )

        existing_duration = _total_duration_minutes(db, application.program_id)
        if existing_duration and not _is_expired(existing, existing_duration):
            raise HTTPException(
                status_code=409,
                detail="A Test A session is already in progress for this application",
            )
        # Existing session found but expired and never submitted: allowed to
        # restart below — falls through and regenerates a fresh question set
        # (a new random shuffle, not the same one reused) rather than just
        # resetting the clock on the stale one.

    try:
        generated_questions, duration_minutes = build_generated_questions(
            db, application.program_id
        )
    except NoTestBlueprintConfigured:
        raise HTTPException(
            status_code=404, detail="No test blueprint configured for this program"
        )
    except InsufficientQuestions as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MalformedQuestion as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if existing is None:
        session = TestASession(application_id=application_id)
        db.add(session)
    else:
        session = existing

    started_at = datetime.now(timezone.utc)
    session.generated_questions = generated_questions
    session.answers = {}
    session.score = None
    session.started_at = started_at
    session.submitted_at = None

    db.commit()
    db.refresh(session)

    return TestASessionStartResponse(
        application_id=session.application_id,
        questions=[
            TestAQuestionOut(
                question_id=uuid.UUID(q["question_id"]),
                question_text=q["question_text"],
                options=q["options"],
                answer_type=q.get("answer_type", "single"),
            )
            for q in session.generated_questions
        ],
        duration_minutes=duration_minutes,
        started_at=session.started_at,
        expires_at=session.started_at + timedelta(minutes=duration_minutes),
    )


@router.post(
    "/applications/{application_id}/test-a-session/submit",
    response_model=TestASessionSubmitResponse,
)
def submit_test_a_session(
    application_id: uuid.UUID,
    payload: TestASessionSubmitRequest,
    db: Session = Depends(get_db),
) -> TestASessionSubmitResponse:
    session = db.get(TestASession, application_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail="No Test A session found — start the test first"
        )

    if session.submitted_at is not None:
        raise HTTPException(
            status_code=409, detail="Test A has already been submitted for this application"
        )

    duration_minutes = _total_duration_minutes(db, session.application.program_id)
    if duration_minutes and _is_expired(session, duration_minutes):
        raise HTTPException(
            status_code=410,
            detail=(
                f"Test A time limit of {duration_minutes} minutes has elapsed — "
                "submission rejected"
            ),
        )

    # submitted_at is always the server's own clock, never client-supplied —
    # trusting a client timestamp here would defeat the expiry check entirely.
    score = grade_submission(session, payload.answers)
    submitted_at = datetime.now(timezone.utc)

    session.answers = {str(k): v for k, v in payload.answers.items()}
    session.score = score
    session.submitted_at = submitted_at
    db.flush()

    # Re-score against PreferenceConfig now that test_a_score is available —
    # the composite score progressively picks up each stage as it completes.
    compute_preference_match(db, session.application)

    db.commit()
    db.refresh(session)

    return TestASessionSubmitResponse(
        application_id=session.application_id,
        score=session.score,
        submitted_at=session.submitted_at,
    )
