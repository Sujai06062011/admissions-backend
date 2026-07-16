import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FinalDecision(Base):
    __tablename__ = "final_decisions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    application: Mapped["Application"] = relationship(back_populates="final_decision")
    decided_by_user: Mapped["AdminUser | None"] = relationship(
        back_populates="final_decisions", foreign_keys=[decided_by]
    )


class Interview(Base):
    __tablename__ = "interviews"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'"))

    application: Mapped["Application"] = relationship(back_populates="interview")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'sent'"))

    application: Mapped["Application"] = relationship(back_populates="notifications")
