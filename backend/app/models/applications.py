"""The credit application and everything attached to it while it is reviewed."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JSONType, utcnow, uuid_pk
from app.models.users import CustomerProfile, User


class CreditApplication(Base):
    __tablename__ = "credit_applications"
    application_id: Mapped[uuid.UUID] = uuid_pk()
    customer_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_profiles.customer_profile_id"), index=True)
    assigned_analyst_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"), index=True)
    application_status: Mapped[str] = mapped_column(String(30), index=True)
    requested_credit_limit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    application_purpose: Mapped[str | None] = mapped_column(String(200))
    customer_response_note: Mapped[str | None] = mapped_column(Text)
    submission_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer_profile: Mapped[CustomerProfile] = relationship()
    assigned_analyst: Mapped[User | None] = relationship(foreign_keys=[assigned_analyst_id])


class Assessment(Base):
    """One LimitForge (AI) evaluation. Advisory only. History is kept (FR-15)."""
    __tablename__ = "assessments"
    assessment_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_versions.rule_version_id"))
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(50))
    assessment_status: Mapped[str] = mapped_column(String(20))          # COMPLETED | FAILED
    spending_forecast: Mapped[float | None] = mapped_column(Numeric(12, 2))
    risk_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    risk_category: Mapped[str | None] = mapped_column(String(10), index=True)
    recommended_credit_limit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    recommendation: Mapped[str | None] = mapped_column(String(40))
    # Top factors behind the score, e.g. [{"code":"HIGH_DTI","label":"...","impact":0.21}] (feature 1)
    reason_codes: Mapped[list | None] = mapped_column(JSONType)
    error_detail: Mapped[str | None] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BureauReport(Base):
    """One credit-bureau pull (fake CIBIL, feature 2)."""
    __tablename__ = "bureau_reports"
    bureau_report_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    report_status: Mapped[str] = mapped_column(String(20))              # COMPLETED | FAILED
    bureau_score: Mapped[int | None] = mapped_column(Integer)           # 300..900
    score_band: Mapped[str | None] = mapped_column(String(20))          # EXCELLENT/GOOD/FAIR/POOR
    active_accounts: Mapped[int | None] = mapped_column(Integer)
    delinquencies_24m: Mapped[int | None] = mapped_column(Integer)
    enquiries_6m: Mapped[int | None] = mapped_column(Integer)
    error_detail: Mapped[str | None] = mapped_column(Text)
    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewNote(Base):
    __tablename__ = "review_notes"
    review_note_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    note_text: Mapped[str] = mapped_column(Text)
    is_info_request: Mapped[bool] = mapped_column(Boolean, default=False)   # True = customer sees it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()


class Assignment(Base):
    __tablename__ = "assignments"
    assignment_id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    analyst_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    assignment_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")   # ACTIVE | REASSIGNED

    analyst: Mapped[User] = relationship(foreign_keys=[analyst_user_id])
    assigned_by: Mapped[User] = relationship(foreign_keys=[assigned_by_user_id])