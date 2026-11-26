"""Seed data. For now: the 4 roles + 6 demo accounts. Later steps add rules and demo cases.

    python -m scripts.seed          # safe to run many times (skips what already exists)
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import CustomerProfile, Role, RoleName, User
from app.services import audit

ROLES = [
    (RoleName.CUSTOMER, "Applies for credit"),
    (RoleName.ANALYST, "Reviews applications"),
    (RoleName.MANAGER, "Decides escalated cases and overrides"),
    (RoleName.ADMIN, "Manages users and rules"),
]

DEMO_USERS = [
    ("Priya Sharma", "customer@finora.dev", "Customer@123", RoleName.CUSTOMER),
    ("Neha Verma", "analyst@finora.dev", "Analyst@123", RoleName.ANALYST),
    ("Rahul Khanna", "analyst2@finora.dev", "Analyst@123", RoleName.ANALYST),
    ("Vikram Malhotra", "manager@finora.dev", "Manager@123", RoleName.MANAGER),
    ("Ananya Iyer", "manager2@finora.dev", "Manager@123", RoleName.MANAGER),  # second manager for maker-checker
    ("Admin User", "admin@finora.dev", "Admin@123", RoleName.ADMIN),
]


def ensure_base(db: Session) -> dict:
    roles = {}
    for name, desc in ROLES:
        r = db.scalars(select(Role).where(Role.role_name == name)).first()
        if r is None:
            r = Role(role_name=name, description=desc)
            db.add(r)
            db.flush()
        roles[name] = r

    users = {}
    for full, email, pw, role in DEMO_USERS:
        u = db.scalars(select(User).where(User.email == email)).first()
        if u is None:
            u = User(full_name=full, email=email, password_hash=hash_password(pw), role_id=roles[role].role_id)
            db.add(u)
            db.flush()
            if role == RoleName.CUSTOMER:
                db.add(CustomerProfile(user_id=u.user_id, customer_reference="CUST-DEMO0001",
                                       annual_income=1_200_000, monthly_expenses=35_000, existing_debt=100_000,
                                       employment_status="SALARIED", credit_history_months=36))
            audit.log_event(db, "USER_SEEDED", f"Seeded demo account {email} ({role})")
        users[email] = u
    return {"roles": roles, "users": users}


def main():
    with SessionLocal() as db:
        ensure_base(db)
        db.commit()
    print("[seed] roles and demo accounts ready")


if __name__ == "__main__":
    main()