import uuid
from datetime import datetime
from typing import Any, List

from sqlalchemy import ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    full_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    applications: Mapped[List["Application"]] = relationship(back_populates="applicant")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("idx_applications_tenant", "tenant_id"),
        Index("idx_applications_program", "program_id"),
        Index("idx_applications_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applicants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'submitted'"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    tenant: Mapped["Tenant"] = relationship(back_populates="applications")
    program: Mapped["Program"] = relationship(back_populates="applications")
    applicant: Mapped["Applicant"] = relationship(back_populates="applications")

    profile_data: Mapped["ProfileData | None"] = relationship(
        back_populates="application", uselist=False
    )
    uploaded_documents: Mapped[List["UploadedDocument"]] = relationship(
        back_populates="application"
    )
    preference_match_result: Mapped["PreferenceMatchResult | None"] = relationship(
        back_populates="application", uselist=False
    )
    admin_decisions: Mapped[List["AdminDecision"]] = relationship(back_populates="application")
    credentials: Mapped["Credential | None"] = relationship(
        back_populates="application", uselist=False
    )
    test_a_session: Mapped["TestASession | None"] = relationship(
        back_populates="application", uselist=False
    )
    test_b_session: Mapped["TestBSession | None"] = relationship(
        back_populates="application", uselist=False
    )
    campus_session: Mapped["CampusSession | None"] = relationship(
        back_populates="application", uselist=False
    )
    final_decision: Mapped["FinalDecision | None"] = relationship(
        back_populates="application", uselist=False
    )
    interview: Mapped["Interview | None"] = relationship(
        back_populates="application", uselist=False
    )
    notifications: Mapped[List["Notification"]] = relationship(back_populates="application")


class ProfileData(Base):
    __tablename__ = "profile_data"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    form_template_version: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    application: Mapped["Application"] = relationship(back_populates="profile_data")


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    ocr_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    application: Mapped["Application"] = relationship(back_populates="uploaded_documents")
