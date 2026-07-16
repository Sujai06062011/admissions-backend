from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scheduling import CampusSchedule, CampusSession
from app.models.stage1 import Application


class NoCampusSchedulesConfigured(Exception):
    """No CampusSchedule rows exist at all for the application's program."""


class CampusFullyBooked(Exception):
    """CampusSchedule rows exist for the program, but all are at capacity."""


def assign_campus_session(db: Session, application: Application) -> CampusSession:
    """Assigns a shortlisted application to the earliest CampusSchedule (by
    session_date) for its program that still has room under capacity.

    Idempotent: if the application already has a CampusSession, returns it
    unchanged rather than reassigning — campus_sessions.application_id is a 1:1
    primary key, so a second assignment would otherwise violate that constraint,
    and silently moving someone to a different date on re-approval would be
    more surprising than useful.

    Raises NoCampusSchedulesConfigured if the program has no CampusSchedule rows
    at all, or CampusFullyBooked if every schedule is at capacity — callers
    should surface these as distinct, actionable errors so an admin knows to
    add more dates. Does not commit; the caller owns the transaction.
    """
    existing = db.get(CampusSession, application.id)
    if existing is not None:
        return existing

    schedules = (
        db.query(CampusSchedule)
        .filter(CampusSchedule.program_id == application.program_id)
        .order_by(CampusSchedule.session_date.asc())
        .all()
    )
    if not schedules:
        raise NoCampusSchedulesConfigured(
            f"No campus schedules configured for program {application.program_id}"
        )

    booked_counts = dict(
        db.query(CampusSession.schedule_id, func.count(CampusSession.application_id))
        .filter(CampusSession.schedule_id.in_([s.id for s in schedules]))
        .group_by(CampusSession.schedule_id)
        .all()
    )

    for schedule in schedules:
        booked = booked_counts.get(schedule.id, 0)
        if booked < schedule.capacity:
            # Assign the relationship object, not just schedule_id: SQLAlchemy's
            # many-to-one lazy loader can return None for .schedule on a
            # freshly-constructed, unflushed object when only the FK column is
            # set — setting the relationship directly avoids that entirely.
            session = CampusSession(application_id=application.id, schedule=schedule)
            db.add(session)
            return session

    raise CampusFullyBooked(
        f"All campus schedules for program {application.program_id} are at capacity"
    )
