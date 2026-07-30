from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.stage1 import Application
from app.models.stage2 import PreferenceConfig, PreferenceMatchResult

# Fields sourced from live session tables rather than the static profile_data
# JSON blob — they only exist once the candidate reaches that stage, which is
# exactly what lets the composite score grow progressively (screening ->
# campus test -> campus interview) as each becomes available.
SESSION_SOURCED_FIELDS = {"test_a_score", "test_b_score"}


def _numeric(value: object) -> float | None:
    """Coerce preference/session values to float.

    Test A scores are stored as SQL Numeric and come back as Decimal — without
    accepting Decimal here, Campus Test reasons permanently store actual=null
    even when the session has a real score.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def normalized_test_b_score(rubric_score: dict | None) -> float | None:
    """Test B's rubric (grammar/fluency/reasoning/coherence) is scored 0-10
    per dimension, while Test A is a 0-100 percentage. Averaging the rubric
    without rescaling would make Test B contribute ~10x less than intended
    for the same configured weight, so the average is scaled onto the same
    0-100 range Test A uses before either is fed into the composite formula.
    """
    if not rubric_score:
        return None
    values = [v for v in rubric_score.values() if isinstance(v, (int, float))]
    return (sum(values) / len(values)) * 10 if values else None


def _session_sourced_actual(application: Application, field_name: str) -> float | None:
    if field_name == "test_a_score":
        return _numeric(application.test_a_session.score) if application.test_a_session else None
    if field_name == "test_b_score":
        return (
            normalized_test_b_score(application.test_b_session.rubric_score)
            if application.test_b_session
            else None
        )
    return None


def compute_preference_match(db: Session, application: Application) -> PreferenceMatchResult:
    """Scores an application against its program's PreferenceConfig rows.

    - hard_pass is False if any is_hard_cutoff config's field is missing from the
      applicant's profile data, non-numeric, below cutoff_value, or has no
      cutoff_value configured at all.
    - composite_score is the weighted sum of soft_weight * actual_value across every
      config with a numeric actual value — hard-cutoff fields contribute too,
      matching the seed data where cutoff fields still carry a nonzero soft_weight.
    - reasons has one entry per config: {field, expected, actual, passed}. For
      hard-cutoff fields, passed means the cutoff was met. For soft-only fields (no
      cutoff), passed means the field was present and numeric in the profile data.
    - test_a_score/test_b_score are read live from the TestASession/TestBSession
      relationships rather than profile_data — they're None until the candidate
      actually reaches that stage, so the composite score is whatever's available
      at call time and is expected to be recomputed again as later stages complete
      (see submit_test_a_session and process_interview_recording).

    Persists onto the application's existing PreferenceMatchResult row (creating one
    if absent) but does not commit — callers own the transaction.
    """
    configs = (
        db.query(PreferenceConfig)
        .filter(PreferenceConfig.program_id == application.program_id)
        .all()
    )
    profile_data = application.profile_data.data if application.profile_data else {}

    reasons = []
    hard_pass = True
    composite_score = 0.0

    for config in configs:
        if config.field_name in SESSION_SOURCED_FIELDS:
            raw_actual = _session_sourced_actual(application, config.field_name)
        else:
            raw_actual = profile_data.get(config.field_name)
        actual = _numeric(raw_actual)

        if config.is_hard_cutoff:
            passed = (
                actual is not None
                and config.cutoff_value is not None
                and actual >= float(config.cutoff_value)
            )
            if not passed:
                hard_pass = False
        else:
            passed = actual is not None

        if actual is not None and config.soft_weight:
            composite_score += float(config.soft_weight) * actual

        reasons.append(
            {
                "field": config.field_name,
                "expected": float(config.cutoff_value) if config.cutoff_value is not None else None,
                "actual": actual if actual is not None else raw_actual,
                "passed": passed,
            }
        )

    result = db.get(PreferenceMatchResult, application.id)
    if result is None:
        result = PreferenceMatchResult(application_id=application.id)
        db.add(result)

    result.composite_score = composite_score
    result.hard_pass = hard_pass
    result.reasons = reasons
    result.computed_at = datetime.now(timezone.utc)

    return result
