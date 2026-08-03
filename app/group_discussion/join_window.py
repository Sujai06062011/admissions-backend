"""Join-window helpers for GD ACS join (default opens T−10 minutes)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.models.group_discussion import GdSession


def default_join_opens_minutes() -> int:
    raw = os.environ.get("GD_JOIN_OPENS_MINUTES_BEFORE", "10").strip()
    try:
        value = int(raw)
    except ValueError:
        return 10
    return max(0, min(value, 120))


def join_opens_at(session: GdSession) -> datetime | None:
    if session.scheduled_at is None:
        return None
    scheduled = session.scheduled_at
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    minutes = session.join_opens_minutes_before
    if minutes is None:
        minutes = default_join_opens_minutes()
    return scheduled - timedelta(minutes=minutes)


def join_window_open(session: GdSession, *, now: datetime | None = None) -> bool:
    """True when candidates may mint an ACS join token."""
    opens = join_opens_at(session)
    if opens is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    # Allow through scheduled end (+ small grace).
    end = session.scheduled_at
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end is not None:
        grace_end = end + timedelta(minutes=session.duration_minutes or 60)
        if current > grace_end:
            return False
    return current >= opens


def topic_visible(session: GdSession) -> bool:
    """Topic is admin-only until host Start."""
    return session.started_at is not None or session.status in {"live", "completed", "scored"}
