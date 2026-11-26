"""Turn database rows into JSON-safe dicts. Each role only ever gets the fields it may see."""
from datetime import datetime, timezone
from decimal import Decimal

from app.models import User


def num(v):
    return float(v) if isinstance(v, Decimal) else v


def iso(dt):
    return dt.isoformat() if dt else None


def user_brief(u: User | None) -> dict | None:
    if u is None:
        return None
    return {"user_id": str(u.user_id), "full_name": u.full_name, "email": u.email, "role": u.role_name}


def serialize_user(u: User) -> dict:
    return {
        **user_brief(u),
        "account_status": u.account_status,
        "is_locked": bool(u.locked_until and u.locked_until > datetime.now(timezone.utc)),
        "last_login_at": iso(u.last_login_at),
        "created_at": iso(u.created_at),
    }