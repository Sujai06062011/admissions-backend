import uuid
from datetime import datetime
from typing import List

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GdSession(Base):
    """One Group Discussion Teams meeting / candidate group.

    Does not change Application.status — pipeline wiring comes later.
    """

    __tablename__ = "gd_sessions"
    __table_args__ = (
        Index("idx_gd_sessions_program", "program_id"),
        Index("idx_gd_sessions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(Text)
    target_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    scheduled_at: Mapped[datetime | None] = mapped_column()
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    assignment_strategy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual'")
    )
    # draft → meeting_ready → invited → cancelled (completed/scored later)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    teams_meeting_id: Mapped[str | None] = mapped_column(Text)
    join_url: Mapped[str | None] = mapped_column(Text)
    professor_email: Mapped[str | None] = mapped_column(Text)
    # Post-meeting artifacts (Teams → Supabase / DB)
    recording_storage_path: Mapped[str | None] = mapped_column(Text)
    recording_graph_id: Mapped[str | None] = mapped_column(Text)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    transcript_vtt: Mapped[str | None] = mapped_column(Text)
    transcript_graph_id: Mapped[str | None] = mapped_column(Text)
    # pending | processing | ready | failed
    artifacts_status: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'"))
    artifacts_error: Mapped[str | None] = mapped_column(Text)
    artifacts_fetched_at: Mapped[datetime | None] = mapped_column()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id")
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    program: Mapped["Program"] = relationship()
    created_by_user: Mapped["AdminUser | None"] = relationship(foreign_keys=[created_by])
    participants: Mapped[List["GdParticipant"]] = relationship(
        back_populates="gd_session", cascade="all, delete-orphan"
    )


class GdParticipant(Base):
    __tablename__ = "gd_participants"
    __table_args__ = (
        UniqueConstraint("gd_session_id", "application_id", name="uq_gd_participant_session_app"),
        Index("idx_gd_participants_application", "application_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    gd_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gd_sessions.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'candidate'"))
    invite_sent_at: Mapped[datetime | None] = mapped_column()
    invite_status: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    gd_session: Mapped["GdSession"] = relationship(back_populates="participants")
    application: Mapped["Application"] = relationship()
