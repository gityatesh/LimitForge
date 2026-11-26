"""Configurable, versioned decision rules (FR-23 to FR-26)."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import JSONType, utcnow, uuid_pk


class DecisionRule(Base):
    __tablename__ = "decision_rules"
    rule_id: Mapped[uuid.UUID] = uuid_pk()
    rule_name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuleVersion(Base):
    """Immutable snapshot of the rule parameters. Editing a rule = adding a new version."""
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version_number"),)
    rule_version_id: Mapped[uuid.UUID] = uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_rules.rule_id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    rule_configuration: Mapped[dict] = mapped_column(JSONType)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))