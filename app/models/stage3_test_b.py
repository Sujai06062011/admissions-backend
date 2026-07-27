import uuid
from datetime import datetime
from typing import Any, List

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PromptBank(Base):
    __tablename__ = "prompt_banks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    program: Mapped["Program"] = relationship(back_populates="prompt_banks")
    prompts: Mapped[List["Prompt"]] = relationship(back_populates="bank")


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (Index("idx_prompts_bank", "bank_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    bank_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_banks.id", ondelete="CASCADE"), nullable=False
    )
    prompt_type: Mapped[str] = mapped_column(Text, nullable=False)
    media_url: Mapped[str | None] = mapped_column(Text)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    bank: Mapped["PromptBank"] = relationship(back_populates="prompts")
    test_b_sessions: Mapped[List["TestBSession"]] = relationship(back_populates="prompt")


class TestBSession(Base):
    __tablename__ = "test_b_sessions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id")
    )
    recording_url: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    rubric_score: Mapped[Any | None] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime | None] = mapped_column()

    # Video proctoring — populated at submit time (snapshot_urls,
    # tab_switch_events) and by the async Claude vision review step
    # (proctoring_review), same lifecycle as rubric_score/rationale above.
    snapshot_urls: Mapped[Any | None] = mapped_column(JSONB)
    tab_switch_events: Mapped[Any | None] = mapped_column(JSONB)
    proctoring_review: Mapped[Any | None] = mapped_column(JSONB)

    application: Mapped["Application"] = relationship(back_populates="test_b_session")
    prompt: Mapped["Prompt | None"] = relationship(back_populates="test_b_sessions")
