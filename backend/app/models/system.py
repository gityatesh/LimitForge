"""Audit trail, alerts, notifications and the email outbox."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import utcnow, uuid_pk
from app.models.users import User


class AuditEvent(Base):
    """Append-only + hash-chained (feature 4).
    hash = SHA-256(prev_hash + this row's content). Editing any old row breaks every hash after it."""
    __tablename__ = "audit_events"
    audit_event_id: Mapped[uuid.UUID] = uuid_pk()
    sequence_number: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_applications.application_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    previous_state: Mapped[str | None] = mapped_column(String(30))
    new_state: Mapped[str | None] = mapped_column(String(30))
    event_description: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    actor: Mapped[User | None] = relationship()


class Alert(Base):
    __tablename__ = "alerts"
    alert_id: Mapped[uuid.UUID] = uuid_pk()
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))                 # INFO | WARNING | CRITICAL
    related_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_applications.application_id"))
    alert_status: Mapped[str] = mapped_column(String(20), default="OPEN")   # OPEN | ACKNOWLEDGED | RESOLVED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    notification_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_applications.application_id"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailOutbox(Base):
    """Outbox pattern (feature 6): the request only QUEUES an email inside its own transaction;
    the worker sends it later. A crashed mail server never breaks a decision."""
    __tablename__ = "email_outbox"
    email_id: Mapped[uuid.UUID] = uuid_pk()
    to_address: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    email_status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING|SENT|FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))