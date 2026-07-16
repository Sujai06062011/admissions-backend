import uuid
from datetime import datetime
from typing import Any, List

from sqlalchemy import ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Credential(Base):
    __tablename__ = "credentials"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    temp_username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    temp_password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    delivered_via: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    login_status: Mapped[str | None] = mapped_column(Text, server_default=text("'not_logged_in'"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    application: Mapped["Application"] = relationship(back_populates="credentials")


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    program: Mapped["Program"] = relationship(back_populates="question_banks")
    questions: Mapped[List["Question"]] = relationship(back_populates="bank")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("idx_questions_bank_category", "bank_id", "category"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    bank_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Any | None] = mapped_column(JSONB)
    correct_answer: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(Text, server_default=text("'medium'"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    bank: Mapped["QuestionBank"] = relationship(back_populates="questions")


class TestBlueprint(Base):
    __tablename__ = "test_blueprints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_threshold: Mapped[float | None] = mapped_column(Numeric)

    program: Mapped["Program"] = relationship(back_populates="test_blueprints")


class TestASession(Base):
    __tablename__ = "test_a_sessions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    generated_questions: Mapped[Any] = mapped_column(JSONB, nullable=False)
    answers: Mapped[Any | None] = mapped_column(JSONB, server_default=text("'{}'"))
    score: Mapped[float | None] = mapped_column(Numeric)
    started_at: Mapped[datetime | None] = mapped_column()
    submitted_at: Mapped[datetime | None] = mapped_column()

    application: Mapped["Application"] = relationship(back_populates="test_a_session")
