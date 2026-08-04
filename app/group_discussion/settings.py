"""Per-program GD settings helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.group_discussion.settings_model import GdProgramSettings

DEFAULT_MIN = 5
DEFAULT_MAX = 7
DEFAULT_DURATION = 30


def get_or_default_settings(db: Session, program_id: uuid.UUID) -> GdProgramSettings:
    row = db.get(GdProgramSettings, program_id)
    if row is not None:
        return row
    return GdProgramSettings(
        program_id=program_id,
        min_group_size=DEFAULT_MIN,
        max_group_size=DEFAULT_MAX,
        default_duration_minutes=DEFAULT_DURATION,
    )


def upsert_settings(
    db: Session,
    program_id: uuid.UUID,
    *,
    min_group_size: int,
    max_group_size: int,
    default_duration_minutes: int,
) -> GdProgramSettings:
    if min_group_size > max_group_size:
        raise ValueError("min_group_size cannot exceed max_group_size")
    row = db.get(GdProgramSettings, program_id)
    if row is None:
        row = GdProgramSettings(program_id=program_id)
        db.add(row)
    row.min_group_size = min_group_size
    row.max_group_size = max_group_size
    row.default_duration_minutes = default_duration_minutes
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    return row
