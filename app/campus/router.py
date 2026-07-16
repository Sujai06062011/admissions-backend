import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.campus.assignment import (
    CampusFullyBooked,
    NoCampusSchedulesConfigured,
    assign_campus_session,
)
from app.campus.schemas import (
    CampusScheduleCreate,
    CampusScheduleResponse,
    CampusScheduleUpdate,
    CampusSessionResponse,
    CheckInRequest,
)
from app.db.session import get_db
from app.models.core import Program
from app.models.scheduling import CampusSchedule, CampusSession
from app.models.stage1 import Application

router = APIRouter(tags=["campus"])


def _with_booked_count(db: Session, schedule: CampusSchedule) -> CampusScheduleResponse:
    booked_count = db.query(CampusSession).filter(CampusSession.schedule_id == schedule.id).count()
    return CampusScheduleResponse(
        id=schedule.id,
        program_id=schedule.program_id,
        session_date=schedule.session_date,
        capacity=schedule.capacity,
        booked_count=booked_count,
    )


def _session_response(session: CampusSession) -> CampusSessionResponse:
    return CampusSessionResponse(
        application_id=session.application_id,
        schedule_id=session.schedule_id,
        session_date=session.schedule.session_date,
        slot_time=session.slot_time,
        check_in_status=session.check_in_status,
        device_id=session.device_id,
    )


# --- CampusSchedule CRUD ---


@router.post(
    "/programs/{program_id}/campus-schedules", response_model=CampusScheduleResponse, status_code=201
)
def create_campus_schedule(
    program_id: uuid.UUID, payload: CampusScheduleCreate, db: Session = Depends(get_db)
) -> CampusScheduleResponse:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    schedule = CampusSchedule(program_id=program_id, **payload.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return _with_booked_count(db, schedule)


@router.get("/programs/{program_id}/campus-schedules", response_model=list[CampusScheduleResponse])
def list_campus_schedules(
    program_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[CampusScheduleResponse]:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    schedules = (
        db.query(CampusSchedule)
        .filter(CampusSchedule.program_id == program_id)
        .order_by(CampusSchedule.session_date)
        .all()
    )
    return [_with_booked_count(db, s) for s in schedules]


@router.get("/campus-schedules/{schedule_id}", response_model=CampusScheduleResponse)
def get_campus_schedule(schedule_id: uuid.UUID, db: Session = Depends(get_db)) -> CampusScheduleResponse:
    schedule = db.get(CampusSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Campus schedule not found")
    return _with_booked_count(db, schedule)


@router.patch("/campus-schedules/{schedule_id}", response_model=CampusScheduleResponse)
def update_campus_schedule(
    schedule_id: uuid.UUID, payload: CampusScheduleUpdate, db: Session = Depends(get_db)
) -> CampusScheduleResponse:
    schedule = db.get(CampusSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Campus schedule not found")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, field_name, value)
    db.commit()
    db.refresh(schedule)
    return _with_booked_count(db, schedule)


@router.delete("/campus-schedules/{schedule_id}", status_code=204)
def delete_campus_schedule(schedule_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    schedule = db.get(CampusSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Campus schedule not found")

    # campus_sessions relationship has no cascade="delete" configured, so a plain
    # session.delete(schedule) would try to null out each session's NOT NULL
    # schedule_id instead of deleting them. Delete the children directly first.
    db.query(CampusSession).filter(CampusSession.schedule_id == schedule_id).delete(
        synchronize_session=False
    )
    db.delete(schedule)
    db.commit()


# --- Assignment ---


@router.post(
    "/applications/{application_id}/assign-campus-session",
    response_model=CampusSessionResponse,
    status_code=201,
)
def assign_campus_session_endpoint(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> CampusSessionResponse:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    try:
        session = assign_campus_session(db, application)
    except NoCampusSchedulesConfigured:
        raise HTTPException(
            status_code=404, detail="No campus schedules configured for this program yet"
        )
    except CampusFullyBooked:
        raise HTTPException(
            status_code=409,
            detail="All campus schedules for this program are fully booked — add more dates",
        )

    db.commit()
    db.refresh(session)
    return _session_response(session)


# --- Check-in ---


@router.post("/applications/{application_id}/campus-check-in", response_model=CampusSessionResponse)
def campus_check_in(
    application_id: uuid.UUID,
    payload: CheckInRequest = CheckInRequest(),
    db: Session = Depends(get_db),
) -> CampusSessionResponse:
    session = db.get(CampusSession, application_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Application has no campus session assigned")

    session.check_in_status = "checked_in"
    if payload.device_id is not None:
        session.device_id = payload.device_id
    db.commit()
    db.refresh(session)
    return _session_response(session)
