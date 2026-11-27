"""FR-05 + feature 10: the customer's own financial profile and bank-statement upload."""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.errors import AppError, not_found
from app.db import get_db
from app.models import BankStatement, CustomerProfile, RoleName, User
from app.schemas.profile import ProfileIn
from app.services import audit
from app.services.serializers import serialize_profile, serialize_statement
from app.services.statement_parser import StatementError, parse_statement

router = APIRouter(prefix="/profile", tags=["profile"])
CUSTOMER = require_roles(RoleName.CUSTOMER)


def own_profile(db: Session, user: User) -> CustomerProfile:
    """Customers only ever touch THEIR profile (FR-04): it is looked up by the logged-in user id."""
    p = db.scalars(select(CustomerProfile).where(CustomerProfile.user_id == user.user_id)).first()
    if p is None:
        raise not_found("Customer profile")
    return p


@router.get("/me")
def get_my_profile(user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    return serialize_profile(own_profile(db, user))


@router.put("/me")
def update_my_profile(body: ProfileIn, user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    p = own_profile(db, user)
    for field, value in body.model_dump().items():
        setattr(p, field, value)
    p.income_source = "MANUAL"          # typed numbers override statement-derived ones
    p.statement_verified = False
    audit.log_event(db, "PROFILE_UPDATED", "Customer updated financial profile (manual)", actor_user_id=user.user_id)
    db.commit()
    db.refresh(p)
    return serialize_profile(p)


@router.post("/me/statement", status_code=201)
async def upload_statement(file: UploadFile = File(...), user: User = Depends(CUSTOMER),
                           db: Session = Depends(get_db)):
    """Upload a bank-statement CSV. We compute average monthly income + expenses and fill the profile."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise AppError(422, "INVALID_FILE_TYPE", "Please upload a .csv file.")
    content = await file.read()
    try:
        summary = parse_statement(content)
    except StatementError as exc:
        raise AppError(422, "INVALID_STATEMENT", str(exc))

    p = own_profile(db, user)
    statement = BankStatement(
        customer_profile_id=p.customer_profile_id, file_name=file.filename[:255],
        transaction_count=summary.transaction_count, months_covered=summary.months_covered,
        avg_monthly_income=summary.avg_monthly_income, avg_monthly_expenses=summary.avg_monthly_expenses,
    )
    db.add(statement)
    p.annual_income = round(summary.avg_monthly_income * 12, 2)
    p.monthly_expenses = summary.avg_monthly_expenses
    p.income_source = "STATEMENT"
    p.statement_verified = True     # = derived from an uploaded statement (not proof it is genuine)
    audit.log_event(db, "STATEMENT_UPLOADED",
                    f"Statement '{file.filename}': {summary.transaction_count} transactions over "
                    f"{summary.months_covered} months", actor_user_id=user.user_id)
    db.commit()
    db.refresh(p)
    return {"profile": serialize_profile(p), "statement": serialize_statement(statement)}


@router.get("/me/statements")
def my_statements(user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    p = own_profile(db, user)
    rows = db.scalars(select(BankStatement).where(BankStatement.customer_profile_id == p.customer_profile_id)
                      .order_by(BankStatement.uploaded_at.desc())).all()
    return [serialize_statement(s) for s in rows]