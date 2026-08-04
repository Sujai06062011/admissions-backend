from datetime import datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy.orm import Session

from app.models.group_discussion import GdParticipant
from app.models.stage1 import Application
from app.models.stage2 import PreferenceConfig, PreferenceMatchResult

# Fields sourced from live session tables rather than the static profile_data
# JSON blob — they only exist once the candidate reaches that stage, which is
# exactly what lets the composite score grow progressively (screening ->
# campus test -> campus interview -> GD) as each becomes available.
SESSION_SOURCED_FIELDS = {"test_a_score", "test_b_score", "gd_score"}

# Default soft_weight when a program has never configured GD (10%).
DEFAULT_GD_SOFT_WEIGHT = 0.10


def ensure_gd_score_preference(db: Session, program_id: uuid.UUID) -> PreferenceConfig:
    """Return the program's gd_score PreferenceConfig, inserting 10% if absent.

    Does not commit — callers own the transaction. Does not overwrite an
    existing row (admin-tuned weights are preserved).
    """
    existing = (
        db.query(PreferenceConfig)
        .filter(
            PreferenceConfig.program_id == program_id,
            PreferenceConfig.field_name == "gd_score",
        )
        .first()
    )
    if existing is not None:
        return existing
    config = PreferenceConfig(
        program_id=program_id,
        field_name="gd_score",
        is_hard_cutoff=False,
        cutoff_value=None,
        soft_weight=DEFAULT_GD_SOFT_WEIGHT,
    )
    db.add(config)
    db.flush()
    return config


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


def normalized_gd_score(overall_score: float | None) -> float | None:
    """GD overall_score is 0-10; scale to 0-100 like Test A / Test B so a
    soft_weight of 0.10 (10%) contributes on the same units as Campus Test.
    """
    if overall_score is None:
        return None
    return float(overall_score) * 10


def latest_gd_overall_score(db: Session, application_id: uuid.UUID) -> float | None:
    """Most recently scored GD overall (0-10), or None if unscored."""
    row = (
        db.query(GdParticipant)
        .filter(
            GdParticipant.application_id == application_id,
            GdParticipant.role == "candidate",
            GdParticipant.overall_score.isnot(None),
        )
        .order_by(GdParticipant.scored_at.desc().nullslast(), GdParticipant.created_at.desc())
        .first()
    )
    return _numeric(row.overall_score) if row is not None else None


def _session_sourced_actual(
    db: Session, application: Application, field_name: str
) -> float | None:
    if field_name == "test_a_score":
        return _numeric(application.test_a_session.score) if application.test_a_session else None
    if field_name == "test_b_score":
        return (
            normalized_test_b_score(application.test_b_session.rubric_score)
            if application.test_b_session
            else None
        )
    if field_name == "gd_score":
        return normalized_gd_score(latest_gd_overall_score(db, application.id))
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
    - test_a_score/test_b_score/gd_score are read live from session tables rather
      than profile_data — they're None until the candidate reaches that stage, so
      the composite score is whatever's available at call time and is expected to
      be recomputed again as later stages complete (see submit_test_a_session,
      process_interview_recording, and score_session).

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
            raw_actual = _session_sourced_actual(db, application, config.field_name)
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
