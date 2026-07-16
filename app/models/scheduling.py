import uuid
from datetime import date, datetime
from typing import List

from sqlalchemy import Date, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CampusSchedule(Base):
    __tablename__ = "campus_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    program: Mapped["Program"] = relationship(back_populates="campus_schedules")
    campus_sessions: Mapped[List["CampusSession"]] = relationship(back_populates="schedule")


class CampusSession(Base):
    __tablename__ = "campus_sessions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campus_schedules.id", ondelete="CASCADE"), nullable=False
    )
    slot_time: Mapped[datetime | None] = mapped_column()
    check_in_status: Mapped[str | None] = mapped_column(Text, server_default=text("'not_checked_in'"))
    device_id: Mapped[str | None] = mapped_column(Text)

    application: Mapped["Application"] = relationship(back_populates="campus_session")
    schedule: Mapped["CampusSchedule"] = relationship(back_populates="campus_sessions")
