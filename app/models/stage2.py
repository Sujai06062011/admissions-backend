import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PreferenceConfig(Base):
    __tablename__ = "preference_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_hard_cutoff: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    cutoff_value: Mapped[float | None] = mapped_column(Numeric)
    soft_weight: Mapped[float | None] = mapped_column(Numeric, server_default=text("0"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    program: Mapped["Program"] = relationship(back_populates="preference_configs")


class PreferenceMatchResult(Base):
    __tablename__ = "preference_match_results"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    composite_score: Mapped[float | None] = mapped_column(Numeric)
    hard_pass: Mapped[bool | None] = mapped_column(Boolean)
    reasons: Mapped[list[Any] | None] = mapped_column(JSONB, server_default=text("'[]'"))
    computed_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    application: Mapped["Application"] = relationship(back_populates="preference_match_result")


class AdminDecision(Base):
    __tablename__ = "admin_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))
    notes: Mapped[str | None] = mapped_column(Text)

    application: Mapped["Application"] = relationship(back_populates="admin_decisions")
    decided_by_user: Mapped["AdminUser | None"] = relationship(
        back_populates="admin_decisions", foreign_keys=[decided_by]
    )
