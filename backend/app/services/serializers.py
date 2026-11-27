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


def serialize_profile(p) -> dict:
    return {
        "customer_profile_id": str(p.customer_profile_id),
        "customer_reference": p.customer_reference,
        "annual_income": num(p.annual_income),
        "monthly_expenses": num(p.monthly_expenses),
        "existing_debt": num(p.existing_debt),
        "employment_status": p.employment_status,
        "credit_history_months": p.credit_history_months,
        "income_source": p.income_source,
        "statement_verified": p.statement_verified,
        "is_complete": p.is_complete(),
        "updated_at": iso(p.updated_at),
    }


def serialize_statement(s) -> dict:
    return {
        "statement_id": str(s.statement_id),
        "file_name": s.file_name,
        "transaction_count": s.transaction_count,
        "months_covered": s.months_covered,
        "avg_monthly_income": num(s.avg_monthly_income),
        "avg_monthly_expenses": num(s.avg_monthly_expenses),
        "uploaded_at": iso(s.uploaded_at),
    }


def serialize_rule_version(v) -> dict:
    return {
        "rule_version_id": str(v.rule_version_id),
        "version_number": v.version_number,
        "rule_configuration": v.rule_configuration,
        "effective_from": iso(v.effective_from),
        "created_by_user_id": str(v.created_by_user_id),
    }