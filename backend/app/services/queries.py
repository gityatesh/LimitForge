"""Filtered, paginated application lists (FR-17, FR-29, NFR-03).
The risk tier comes from each application's LATEST assessment (grouped subquery: fast on 10k rows)."""
import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, aliased

from app.models import AppStatus, Assessment, CreditApplication, CustomerProfile, User

LatestA = aliased(Assessment)


def latest_assessment_subquery():
    return (select(Assessment.application_id, func.max(Assessment.assessed_at).label("max_at"))
            .group_by(Assessment.application_id).subquery())


def build_application_query(*, customer_profile_id: uuid.UUID | None = None, status: str | None = None,
                            date_from: date | None = None, date_to: date | None = None,
                            assigned_analyst_id: uuid.UUID | None = None, risk_category: str | None = None,
                            unassigned_only: bool = False, exclude_drafts: bool = True) -> Select:
    latest = latest_assessment_subquery()
    q = (select(CreditApplication, LatestA, CustomerProfile, User)
         .join(CustomerProfile, CreditApplication.customer_profile_id == CustomerProfile.customer_profile_id)
         .join(User, CustomerProfile.user_id == User.user_id)
         .outerjoin(latest, latest.c.application_id == CreditApplication.application_id)
         .outerjoin(LatestA, and_(LatestA.application_id == CreditApplication.application_id,
                                  LatestA.assessed_at == latest.c.max_at)))
    if customer_profile_id:
        q = q.where(CreditApplication.customer_profile_id == customer_profile_id)
    if exclude_drafts:
        q = q.where(CreditApplication.application_status != AppStatus.DRAFT)
    if status:
        q = q.where(CreditApplication.application_status.in_([s.strip().upper() for s in status.split(",") if s.strip()]))
    if date_from:
        q = q.where(CreditApplication.submission_date >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(CreditApplication.submission_date <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    if assigned_analyst_id:
        q = q.where(CreditApplication.assigned_analyst_id == assigned_analyst_id)
    if unassigned_only:
        q = q.where(CreditApplication.assigned_analyst_id.is_(None))
    if risk_category:
        q = q.where(LatestA.risk_category == risk_category.upper())
    return q


def paginate(db: Session, q: Select, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = db.execute(q.order_by(func.coalesce(CreditApplication.submission_date, CreditApplication.updated_at).desc(),
                                 CreditApplication.application_id)
                      .limit(page_size).offset((page - 1) * page_size)).all()
    return total, rows