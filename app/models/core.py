import uuid
from datetime import datetime
from typing import List

from sqlalchemy import Boolean, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    programs: Mapped[List["Program"]] = relationship(back_populates="tenant")
    admin_users: Mapped[List["AdminUser"]] = relationship(back_populates="tenant")
    applications: Mapped[List["Application"]] = relationship(back_populates="tenant")


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    tenant: Mapped["Tenant"] = relationship(back_populates="programs")
    applications: Mapped[List["Application"]] = relationship(back_populates="program")
    preference_configs: Mapped[List["PreferenceConfig"]] = relationship(back_populates="program")
    question_banks: Mapped[List["QuestionBank"]] = relationship(back_populates="program")
    test_blueprints: Mapped[List["TestBlueprint"]] = relationship(back_populates="program")
    prompt_banks: Mapped[List["PromptBank"]] = relationship(back_populates="program")
    campus_schedules: Mapped[List["CampusSchedule"]] = relationship(back_populates="program")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'admin'"))
    # Nullable: an admin row can exist (e.g. seeded) before a password is set.
    # Login must reject rows where this is null rather than treating "no
    # password set" as "any password works."
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    tenant: Mapped["Tenant"] = relationship(back_populates="admin_users")
    admin_decisions: Mapped[List["AdminDecision"]] = relationship(back_populates="decided_by_user")
    final_decisions: Mapped[List["FinalDecision"]] = relationship(back_populates="decided_by_user")
