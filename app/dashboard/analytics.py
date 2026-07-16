import uuid

from sqlalchemy.orm import Session

from app.models.scheduling import CampusSession
from app.models.stage1 import Application
from app.models.stage2 import AdminDecision, PreferenceMatchResult
from app.models.stage3_test_a import TestASession
from app.models.stage3_test_b import TestBSession


def compute_funnel(db: Session, program_id: uuid.UUID) -> dict[str, int]:
    """Computes funnel stage counts for a program.

    Each count is cumulative — "reached at least this stage" — not "currently
    sitting in exactly this status". application.status is a single mutable
    field that only reflects the application's latest stage, so an applicant
    who was moved to campus and has since been called for interview would be
    missed by a naive `status == 'moved_to_campus'` filter. Instead, each
    stage (other than 'received' and 'offered') is counted from durable
    evidence that the stage was actually reached:

    - received: every application submitted for the program.
    - rejected_on_preference_match: PreferenceMatchResult.hard_pass is False
      — specifically the Stage 2 automated cutoff rejection, not rejection at
      any later stage.
    - moved_to_campus: a CampusSession row exists — created exactly once,
      at the point an application is moved to campus, and never removed.
    - test_a_complete: TestASession.submitted_at is set — the candidate
      finished the test, regardless of score.
    - test_b_complete: TestBSession.recording_url is set — the candidate
      submitted their interview recording. Deliberately not gated on
      rubric_score, since AI scoring is an async background step that can
      fail independently of whether the candidate completed their part.
    - called_for_interview: an AdminDecision row exists with
      stage='stage3_call_for_interview' and decision in
      ('approved','manual_override') — counted from the decision event
      itself (deduplicated) rather than application.status, since status
      moves on to 'offered' afterward and would otherwise undercount.
    - offered: application.status == 'offered'. This is the one stage still
      read from application.status directly, because it's a terminal state
      nothing moves past, and no other endpoint currently records an offer
      anywhere else (FinalDecision exists as a model but nothing writes to
      it yet).
    """
    base = db.query(Application).filter(Application.program_id == program_id)

    received = base.count()

    rejected_on_preference_match = (
        base.join(PreferenceMatchResult, Application.id == PreferenceMatchResult.application_id)
        .filter(PreferenceMatchResult.hard_pass.is_(False))
        .count()
    )

    moved_to_campus = base.join(
        CampusSession, Application.id == CampusSession.application_id
    ).count()

    test_a_complete = (
        base.join(TestASession, Application.id == TestASession.application_id)
        .filter(TestASession.submitted_at.isnot(None))
        .count()
    )

    test_b_complete = (
        base.join(TestBSession, Application.id == TestBSession.application_id)
        .filter(TestBSession.recording_url.isnot(None))
        .count()
    )

    called_for_interview = (
        base.join(AdminDecision, Application.id == AdminDecision.application_id)
        .filter(
            AdminDecision.stage == "stage3_call_for_interview",
            AdminDecision.decision.in_(["approved", "manual_override"]),
        )
        .distinct()
        .count()
    )

    offered = base.filter(Application.status == "offered").count()

    return {
        "received": received,
        "rejected_on_preference_match": rejected_on_preference_match,
        "moved_to_campus": moved_to_campus,
        "test_a_complete": test_a_complete,
        "test_b_complete": test_b_complete,
        "called_for_interview": called_for_interview,
        "offered": offered,
    }
