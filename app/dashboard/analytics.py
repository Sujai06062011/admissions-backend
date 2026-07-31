import uuid

from sqlalchemy.orm import Session, selectinload

from app.models.scheduling import CampusSession
from app.models.stage1 import Application
from app.models.stage2 import AdminDecision, PreferenceMatchResult
from app.models.stage3_test_a import TestASession
from app.models.stage3_test_b import TestBSession

# Statuses that mean the candidate has already left the screening hold pool —
# same gate deriveStage uses before it can return screening_rejected.
_ADVANCED_PAST_SCREENING = frozenset(
    {"moved_to_campus", "testing_complete", "called_for_interview", "offered"}
)


def has_data_mismatch(profile_data) -> bool:
    """True when the candidate submitted after acknowledging OCR/name
    mismatches — profile_data.data["data_mismatches"] is written by the
    Confirm & Submit consent screen. Missing/empty means a clean submit.
    """
    if profile_data is None or not isinstance(profile_data.data, dict):
        return False
    mismatches = profile_data.data.get("data_mismatches")
    if not isinstance(mismatches, dict):
        return False
    names = mismatches.get("name_mismatches") or []
    edits = mismatches.get("edited_fields") or []
    return bool(names) or bool(edits)


def _is_screening_rejected(
    *,
    status: str,
    hard_pass: bool | None,
    is_overridden: bool,
    data_mismatch: bool,
) -> bool:
    """Mirrors frontend lib/adminPipeline.ts deriveStage → screening_rejected.

    Once a candidate has advanced past screening (campus / interview / offer),
    they are no longer counted as a screening reject — even if hard_pass is
    still false from an earlier preference compute.
    """
    if status in _ADVANCED_PAST_SCREENING:
        return False
    if is_overridden:
        return False
    if data_mismatch:
        return True
    if hard_pass is False:
        return True
    return False


def compute_funnel(db: Session, program_id: uuid.UUID) -> dict[str, int]:
    """Computes funnel stage counts for a program.

    Each later-stage count is cumulative — "reached at least this stage" — not
    "currently sitting in exactly this status". application.status is a single
    mutable field that only reflects the application's latest stage, so an
    applicant who was moved to campus and has since been called for interview
    would be missed by a naive `status == 'moved_to_campus'` filter. Instead,
    each stage (other than 'received' and 'offered') is counted from durable
    evidence that the stage was actually reached:

    - received: every application submitted for the program.
    - rejected_on_preference_match: candidates who would show as
      "Rejected at Screening" in the Applications UI (hard_pass false and/or
      data mismatch, not overridden, and not yet advanced past screening).
      Kept under this field name for API compatibility; Overview uses
      received - this count as Passed Screening so it matches Applications.
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
    - offered: application.status == 'offered'.
    """
    base = db.query(Application).filter(Application.program_id == program_id)

    applications = (
        base.options(
            selectinload(Application.preference_match_result),
            selectinload(Application.profile_data),
        ).all()
    )
    received = len(applications)

    overridden_ids = {
        row[0]
        for row in db.query(AdminDecision.application_id)
        .filter(
            AdminDecision.stage == "stage2_move_to_campus",
            AdminDecision.decision == "manual_override",
        )
        .all()
    }

    rejected_on_preference_match = 0
    for app in applications:
        hard_pass = (
            app.preference_match_result.hard_pass if app.preference_match_result else None
        )
        if _is_screening_rejected(
            status=app.status,
            hard_pass=hard_pass,
            is_overridden=app.id in overridden_ids,
            data_mismatch=has_data_mismatch(app.profile_data),
        ):
            rejected_on_preference_match += 1

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
