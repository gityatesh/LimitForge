"""Applications: customer drafts/submits/withdraws; everyone lists and views what they may see.
FR-04, FR-06..FR-10, FR-16, FR-17, FR-29."""
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.core.errors import AppError, conflict, forbidden, not_found
from app.db import get_db
from app.models import AppStatus, AuditEvent, CreditApplication, CustomerProfile, Decision, ReviewNote, RoleName, User
from app.routers.profile import own_profile
from app.schemas.applications import MAX_LIMIT, MIN_LIMIT, DraftIn, SubmitIn
from app.services.queries import build_application_query, paginate
from app.services.rules_engine import get_active_rule_version
from app.services.serializers import iso, num
from app.services.views import SYNTHETIC_NOTICE, can_withdraw, serialize_application_customer, serialize_application_staff
from app.services.workflow import LABELS, change_state, run_assessment

router = APIRouter(prefix="/applications", tags=["applications"])
CUSTOMER = require_roles(RoleName.CUSTOMER)


# ------------------------------------------------------------------ helpers
def active_config(db: Session) -> dict | None:
    try:
        return get_active_rule_version(db).rule_configuration
    except AppError:
        return None


def get_own_application(db: Session, user: User, application_id: uuid.UUID) -> CreditApplication:
    """404 (not 403) for someone else's application, so ids cannot be probed (FR-04)."""
    profile = own_profile(db, user)
    app = db.get(CreditApplication, application_id)
    if app is None or app.customer_profile_id != profile.customer_profile_id:
        raise not_found("Application")
    return app


def get_staff_application(db: Session, application_id: uuid.UUID) -> CreditApplication:
    """Staff never see drafts: a draft is not yet an application to the bank."""
    app = db.get(CreditApplication, application_id)
    if app is None or app.application_status == AppStatus.DRAFT:
        raise not_found("Application")
    return app


def _require_complete_profile(profile: CustomerProfile) -> None:
    if not profile.is_complete():
        raise AppError(422, "PROFILE_INCOMPLETE",
                       "Complete your financial profile (income, expenses, debt, employment, credit history) first.")


def _submit(db: Session, app: CreditApplication, profile: CustomerProfile, user: User) -> None:
    """Draft/new -> Submitted, then pull bureau + AI assessment in the same transaction."""
    change_state(db, app, AppStatus.SUBMITTED, user, "APPLICATION_SUBMITTED",
                 f"Customer submitted application for {float(app.requested_credit_limit):,.0f}")
    app.submission_date = datetime.now(timezone.utc)
    run_assessment(db, app, profile, user, reason="submission")


# ------------------------------------------------------------------ customer actions
@router.post("/draft", status_code=201)
def create_draft(body: DraftIn, user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    profile = own_profile(db, user)
    app = CreditApplication(application_id=uuid.uuid4(), customer_profile_id=profile.customer_profile_id,
                            application_status=None, requested_credit_limit=body.requested_credit_limit,
                            application_purpose=body.application_purpose)
    db.add(app)
    change_state(db, app, AppStatus.DRAFT, user, "DRAFT_SAVED", "Customer saved a draft application")
    db.commit()
    return serialize_application_customer(db, app, active_config(db))


@router.put("/{application_id}")
def update_draft(application_id: uuid.UUID, body: DraftIn, user: User = Depends(CUSTOMER),
                 db: Session = Depends(get_db)):
    app = get_own_application(db, user, application_id)
    if app.application_status != AppStatus.DRAFT:
        raise conflict("NOT_A_DRAFT", "Only draft applications can be edited.")
    app.requested_credit_limit = body.requested_credit_limit
    app.application_purpose = body.application_purpose
    db.commit()
    return serialize_application_customer(db, app, active_config(db))


@router.post("", status_code=201)
def submit_new(body: SubmitIn, user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    profile = own_profile(db, user)
    _require_complete_profile(profile)
    app = CreditApplication(application_id=uuid.uuid4(), customer_profile_id=profile.customer_profile_id,
                            application_status=None, requested_credit_limit=body.requested_credit_limit,
                            application_purpose=body.application_purpose)
    db.add(app)
    _submit(db, app, profile, user)
    db.commit()
    return serialize_application_customer(db, app, active_config(db))


@router.post("/{application_id}/submit")
def submit_draft(application_id: uuid.UUID, user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    app = get_own_application(db, user, application_id)
    if app.application_status != AppStatus.DRAFT:
        raise conflict("NOT_A_DRAFT", "Only drafts can be submitted this way.")
    # FR-07: the stored draft must pass the SAME strict rules as a direct submission
    problems = []
    if not app.requested_credit_limit or not (MIN_LIMIT <= float(app.requested_credit_limit) <= MAX_LIMIT):
        problems.append({"field": "requested_credit_limit", "message": f"Must be between {MIN_LIMIT:,} and {MAX_LIMIT:,}"})
    if not app.application_purpose or len(app.application_purpose.strip()) < 3:
        problems.append({"field": "application_purpose", "message": "At least 3 characters"})
    if problems:
        raise AppError(422, "VALIDATION_ERROR", "The draft is incomplete.", problems)
    _require_complete_profile(app.customer_profile)
    _submit(db, app, app.customer_profile, user)
    db.commit()
    return serialize_application_customer(db, app, active_config(db))


@router.post("/{application_id}/withdraw")
def withdraw(application_id: uuid.UUID, user: User = Depends(CUSTOMER), db: Session = Depends(get_db)):
    app = get_own_application(db, user, application_id)
    config = active_config(db)
    if app.application_status == AppStatus.SUBMITTED and not can_withdraw(app, config):
        raise conflict("WITHDRAWAL_NOT_PERMITTED", "Active rules do not allow withdrawal after submission.")
    change_state(db, app, AppStatus.WITHDRAWN, user, "APPLICATION_WITHDRAWN", "Customer withdrew the application")
    db.commit()
    return serialize_application_customer(db, app, config)


# ------------------------------------------------------------------ lists and detail
@router.get("")
def list_applications(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    assigned_analyst_id: uuid.UUID | None = None,
    risk_category: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
    mine: bool = False,
    unassigned: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(require_roles(RoleName.CUSTOMER, RoleName.ANALYST, RoleName.MANAGER)),
    db: Session = Depends(get_db),
):
    is_customer = user.role_name == RoleName.CUSTOMER
    if is_customer:
        q = build_application_query(customer_profile_id=own_profile(db, user).customer_profile_id,
                                    status=status, exclude_drafts=False)
    else:
        q = build_application_query(status=status, date_from=date_from, date_to=date_to,
                                    assigned_analyst_id=user.user_id if mine else assigned_analyst_id,
                                    risk_category=risk_category, unassigned_only=unassigned)
    total, rows = paginate(db, q, page, page_size)
    items = []
    for app, a, profile, cust in rows:
        item = {"application_id": str(app.application_id), "application_status": app.application_status,
                "status_label": LABELS[app.application_status],
                "requested_credit_limit": num(app.requested_credit_limit),
                "application_purpose": app.application_purpose,
                "submission_date": iso(app.submission_date), "updated_at": iso(app.updated_at)}
        if not is_customer:
            item.update({"customer_name": cust.full_name, "customer_reference": profile.customer_reference,
                         "assigned_analyst_id": str(app.assigned_analyst_id) if app.assigned_analyst_id else None,
                         "risk_category": a.risk_category if a else None, "risk_score": num(a.risk_score) if a else None,
                         "recommendation": a.recommendation if a else None,
                         "assessment_status": a.assessment_status if a else None})
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "notice": SYNTHETIC_NOTICE}


@router.get("/{application_id}")
def get_application(application_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role_name == RoleName.CUSTOMER:
        return serialize_application_customer(db, get_own_application(db, user, application_id), active_config(db))
    if user.role_name in (RoleName.ANALYST, RoleName.MANAGER):
        return serialize_application_staff(db, get_staff_application(db, application_id), user)
    raise forbidden()


@router.get("/{application_id}/audit")
def application_audit(application_id: uuid.UUID,
                      user: User = Depends(require_roles(RoleName.ANALYST, RoleName.MANAGER, RoleName.ADMIN)),
                      db: Session = Depends(get_db)):
    app = db.get(CreditApplication, application_id)
    if app is None:
        raise not_found("Application")
    if user.role_name == RoleName.ANALYST:
        # Analysts see trails only for cases assigned to, noted on or decided by them (RBAC Condition 3)
        involved = (app.assigned_analyst_id == user.user_id
                    or db.scalars(select(ReviewNote.review_note_id).where(
                        ReviewNote.application_id == application_id, ReviewNote.author_user_id == user.user_id)).first()
                    or db.scalars(select(Decision.decision_id).where(
                        Decision.application_id == application_id, Decision.decided_by_user_id == user.user_id)).first())
        if not involved:
            raise forbidden("Analysts can view audit trails only for applications they worked on.")
    events = db.scalars(select(AuditEvent).where(AuditEvent.application_id == application_id)
                        .order_by(AuditEvent.sequence_number)).all()
    return [{"sequence_number": e.sequence_number, "event_type": e.event_type, "previous_state": e.previous_state,
             "new_state": e.new_state, "event_description": e.event_description, "timestamp": iso(e.timestamp),
             "actor": {"full_name": e.actor.full_name, "role": e.actor.role_name} if e.actor else None}
            for e in events]