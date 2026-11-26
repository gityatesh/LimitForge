"""Final decisions, maker-checker approvals and appeals."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import utcnow, uuid_pk
from app.models.users import User


class Decision(Base):
    """A FINAL human decision. Append-only: never updated or deleted (FR-28).
    At most one INITIAL decision and one APPEAL decision per application."""
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("application_id", "decision_stage"),)
    decision_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    decision_stage: Mapped[str] = mapped_column(String(20), default="INITIAL")   # INITIAL | APPEAL
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assessments.assessment_id"))
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    # Set when a second manager confirmed it (maker-checker, feature 3)
    second_approver_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    decision_outcome: Mapped[str] = mapped_column(String(20))                    # APPROVED | REJECTED
    approved_credit_limit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_reason: Mapped[str | None] = mapped_column(Text)                    # internal only
    customer_explanation: Mapped[str] = mapped_column(Text)                      # customer sees this
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    decided_by: Mapped[User] = relationship(foreign_keys=[decided_by_user_id])
    second_approver: Mapped[User | None] = relationship(foreign_keys=[second_approver_user_id])


class ApprovalRequest(Base):
    """Maker-checker: a large override proposed by one manager, waiting for a second one."""
    __tablename__ = "approval_requests"
    approval_request_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    decision_stage: Mapped[str] = mapped_column(String(20), default="INITIAL")
    proposed_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    proposed_outcome: Mapped[str] = mapped_column(String(20))
    proposed_credit_limit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    decision_reason: Mapped[str] = mapped_column(Text)
    customer_explanation: Mapped[str] = mapped_column(Text)
    request_status: Mapped[str] = mapped_column(String(20), default="PENDING")   # PENDING | CONFIRMED | DECLINED
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    proposed_by: Mapped[User] = relationship(foreign_keys=[proposed_by_user_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_user_id])


class Appeal(Base):
    """A customer may appeal a rejection ONCE (unique application_id, feature 9)."""
    __tablename__ = "appeals"
    appeal_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), unique=True)
    appeal_reason: Mapped[str] = mapped_column(Text)
    appeal_status: Mapped[str] = mapped_column(String(20), default="OPEN")       # OPEN | UPHELD | DENIED
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))