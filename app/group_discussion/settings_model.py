"""Program-level Group Discussion settings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GdProgramSettings(Base):
    __tablename__ = "gd_program_settings"

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    min_group_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    max_group_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("7"))
    default_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    updated_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))
