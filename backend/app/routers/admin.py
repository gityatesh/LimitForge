"""FR-03: admin manages users, roles, account status and lockouts."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.errors import AppError, not_found
from app.core.security import hash_password
from app.db import get_db
from app.models import AccountStatus, CustomerProfile, Role, RoleName, User
from app.routers.auth import new_customer_reference
from app.schemas.auth import AdminUserCreateIn, RoleChangeIn, StatusChangeIn
from app.services import audit
from app.services.serializers import serialize_user

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN = require_roles(RoleName.ADMIN)


def _role(db: Session, name: str) -> Role:
    return db.scalars(select(Role).where(Role.role_name == name)).one()


def _get_other_user(db: Session, user_id: uuid.UUID, admin: User) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise not_found("User")
    if target.user_id == admin.user_id:
        raise AppError(409, "CANNOT_MODIFY_SELF", "You cannot change your own role or status.")
    return target


def _ensure_profile(db: Session, user: User) -> None:
    exists = db.scalars(select(CustomerProfile).where(CustomerProfile.user_id == user.user_id)).first()
    if not exists:
        db.add(CustomerProfile(user_id=user.user_id, customer_reference=new_customer_reference()))


@router.get("/users")
def list_users(role: str | None = None, q: str | None = None, user: User = Depends(ADMIN),
               db: Session = Depends(get_db)):
    query = select(User).join(Role)
    if role:
        query = query.where(Role.role_name == role.upper())
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    return [serialize_user(u) for u in db.scalars(query.order_by(User.created_at).limit(500)).all()]


@router.get("/analysts")
def list_analysts(user: User = Depends(require_roles(RoleName.MANAGER, RoleName.ADMIN)),
                  db: Session = Depends(get_db)):
    """Managers need this list to assign cases."""
    q = select(User).join(Role).where(Role.role_name == RoleName.ANALYST, User.account_status == AccountStatus.ACTIVE)
    return [serialize_user(u) for u in db.scalars(q).all()]


@router.post("/users", status_code=201)
def create_user(body: AdminUserCreateIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise AppError(409, "EMAIL_IN_USE", "An account with this email already exists.")
    new = User(full_name=body.full_name, email=email, password_hash=hash_password(body.password),
               role_id=_role(db, body.role).role_id)
    db.add(new)
    db.flush()
    if body.role == RoleName.CUSTOMER:
        _ensure_profile(db, new)
    audit.log_event(db, "USER_CREATED", f"Admin created {body.role} account {email}", actor_user_id=user.user_id)
    db.commit()
    db.refresh(new)
    return serialize_user(new)


@router.patch("/users/{user_id}/role")
def change_role(user_id: uuid.UUID, body: RoleChangeIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    target = _get_other_user(db, user_id, user)
    old = target.role_name
    if old != body.role:
        target.role_id = _role(db, body.role).role_id
        if body.role == RoleName.CUSTOMER:
            _ensure_profile(db, target)
        audit.log_event(db, "ROLE_CHANGED", f"{target.email}: {old} -> {body.role}", actor_user_id=user.user_id)
        db.commit()
        db.expire(target)
    return serialize_user(db.get(User, user_id))


@router.patch("/users/{user_id}/status")
def change_status(user_id: uuid.UUID, body: StatusChangeIn, user: User = Depends(ADMIN),
                  db: Session = Depends(get_db)):
    target = _get_other_user(db, user_id, user)
    target.account_status = body.account_status
    audit.log_event(db, "ACCOUNT_STATUS_CHANGED", f"{target.email} set to {body.account_status}",
                    actor_user_id=user.user_id)
    db.commit()
    return serialize_user(target)


@router.post("/users/{user_id}/unlock")
def unlock(user_id: uuid.UUID, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    target = _get_other_user(db, user_id, user)
    target.locked_until = None
    target.failed_login_count = 0
    audit.log_event(db, "ACCOUNT_UNLOCKED", f"{target.email} unlocked by admin", actor_user_id=user.user_id)
    db.commit()
    return serialize_user(target)