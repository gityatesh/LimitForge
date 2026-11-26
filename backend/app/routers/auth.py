"""FR-01: register, login (with lockout + rate limit), logout, me."""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.db import get_db
from app.models import AccountStatus, CustomerProfile, Role, RoleName, User
from app.schemas.auth import LoginIn, RegisterIn
from app.services import audit
from app.services.serializers import serialize_user

router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Invalid email or password."


def new_customer_reference() -> str:
    return f"CUST-{secrets.token_hex(4).upper()}"


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(settings.cookie_name, token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=settings.jwt_expire_minutes * 60, path="/")


def _login_response(response: Response, user: User) -> dict:
    token = create_access_token(str(user.user_id), user.role_name)
    _set_cookie(response, token)
    return {"user": serialize_user(user), "access_token": token, "token_type": "bearer"}


@router.post("/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise AppError(409, "EMAIL_IN_USE", "An account with this email already exists.")
    role = db.scalars(select(Role).where(Role.role_name == RoleName.CUSTOMER)).one()
    user = User(full_name=body.full_name, email=email, password_hash=hash_password(body.password),
                role_id=role.role_id)
    db.add(user)
    db.flush()
    db.add(CustomerProfile(user_id=user.user_id, customer_reference=new_customer_reference()))
    audit.log_event(db, "USER_REGISTERED", f"Customer account registered ({email})", actor_user_id=user.user_id)
    db.commit()
    db.refresh(user)
    return _login_response(response, user)


@router.post("/login", dependencies=[Depends(rate_limit(limit=10))])
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    user = db.scalars(select(User).where(User.email == body.email.lower())).first()

    # 1. Unknown email: same message as a wrong password, so attackers can't discover accounts
    if user is None:
        audit.log_event(db, "LOGIN_FAILED", "Failed sign-in attempt (unknown account)")
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", GENERIC_LOGIN_ERROR)

    # 2. Currently locked out
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AppError(403, "ACCOUNT_LOCKED", f"Too many failed attempts. Try again in {minutes} minute(s).")

    # 3. Wrong password: count it, lock on the 5th
    if not verify_password(body.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
            audit.log_event(db, "ACCOUNT_LOCKED",
                            f"Locked for {settings.lockout_minutes} min after {settings.max_failed_logins} failed attempts",
                            actor_user_id=user.user_id)
        else:
            audit.log_event(db, "LOGIN_FAILED", "Failed sign-in attempt (wrong password)", actor_user_id=user.user_id)
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", GENERIC_LOGIN_ERROR)

    # 4. Right password but disabled by an admin
    if user.account_status != AccountStatus.ACTIVE:
        audit.log_event(db, "LOGIN_BLOCKED", "Sign-in blocked: account disabled", actor_user_id=user.user_id)
        db.commit()
        raise AppError(403, "ACCOUNT_DISABLED", "This account has been disabled. Contact an administrator.")

    # 5. Success
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    audit.log_event(db, "LOGIN_SUCCESS", "User signed in", actor_user_id=user.user_id)
    db.commit()
    return _login_response(response, user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return serialize_user(user)