from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.stage1 import Application
from app.models.stage2 import PreferenceConfig, PreferenceMatchResult


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
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
