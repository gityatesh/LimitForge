"""Alerts for staff (FR-32). Adds to the current transaction; the caller commits."""
import uuid

from sqlalchemy.orm import Session

from app.models import Alert


def raise_alert(db: Session, alert_type: str, message: str, severity: str,
                application_id: uuid.UUID | None = None) -> Alert:
    a = Alert(alert_type=alert_type, message=message, severity=severity, related_application_id=application_id)
    db.add(a)
    return a