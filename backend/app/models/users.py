"""Who can log in, and the customer's financial profile."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import utcnow, uuid_pk


class Role(Base):
    __tablename__ = "roles"
    role_id: Mapped[uuid.UUID] = uuid_pk()
    role_name: Mapped[str] = mapped_column(String(20), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[uuid.UUID] = uuid_pk()
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.role_id"))
    account_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    # Login protection (feature 5)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    role: Mapped[Role] = relationship(lazy="joined")

    @property
    def role_name(self) -> str:
        return self.role.role_name


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    customer_profile_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), unique=True)
    customer_reference: Mapped[str] = mapped_column(String(32), unique=True)
    annual_income: Mapped[float | None] = mapped_column(Numeric(12, 2))
    monthly_expenses: Mapped[float | None] = mapped_column(Numeric(12, 2))
    existing_debt: Mapped[float | None] = mapped_column(Numeric(12, 2))
    employment_status: Mapped[str | None] = mapped_column(String(20))
    credit_history_months: Mapped[int | None] = mapped_column(Integer)
    # Where income/expenses came from: MANUAL (typed) or STATEMENT (CSV upload, feature 10)
    income_source: Mapped[str] = mapped_column(String(20), default="MANUAL")
    statement_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()

    def is_complete(self) -> bool:
        return None not in (self.annual_income, self.monthly_expenses, self.existing_debt,
                            self.employment_status, self.credit_history_months)


class BankStatement(Base):
    """One uploaded bank-statement CSV and what we calculated from it (feature 10)."""
    __tablename__ = "bank_statements"
    statement_id: Mapped[uuid.UUID] = uuid_pk()
    customer_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_profiles.customer_profile_id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    transaction_count: Mapped[int] = mapped_column(Integer)
    months_covered: Mapped[int] = mapped_column(Integer)
    avg_monthly_income: Mapped[float] = mapped_column(Numeric(12, 2))
    avg_monthly_expenses: Mapped[float] = mapped_column(Numeric(12, 2))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordResetToken(Base):
    """Single-use reset token (feature 7). Only a HASH of the token is stored."""
    __tablename__ = "password_reset_tokens"
    token_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)