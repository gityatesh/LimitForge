"""Authentication + RBAC guards (FR-02, NFR-05).

Every protected endpoint declares   user = Depends(require_roles(...))
The user is loaded from the DATABASE on every request, so a disabled account or a
changed role takes effect immediately, even if the old token has not expired yet.
"""
import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import AppError, forbidden
from app.core.security import decode_access_token
from app.db import get_db
from app.models import AccountStatus, User


# Declaring this scheme makes Swagger show the "Authorize" button.
# auto_error=False: if the header is missing we fall back to the cookie instead of failing.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from /auth/login")


def _extract_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    """Accept 'Authorization: Bearer <token>' (Swagger, tests) or the httpOnly cookie (browser)."""
    if creds and creds.scheme.lower() == "bearer":
        return creds.credentials
    return request.cookies.get(settings.cookie_name)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, creds)
    payload = decode_access_token(token) if token else None
    if not payload:
        raise AppError(401, "UNAUTHENTICATED", "Please sign in to continue.")
    try:
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (ValueError, KeyError):
        user = None
    if user is None:
        raise AppError(401, "UNAUTHENTICATED", "Please sign in to continue.")
    if user.account_status != AccountStatus.ACTIVE:
        raise AppError(403, "ACCOUNT_DISABLED", "This account has been disabled.")
    return user


def require_roles(*roles: str):
    """Usage: user: User = Depends(require_roles(RoleName.MANAGER, RoleName.ADMIN))"""

    def guard(user: User = Depends(get_current_user)) -> User:
        if user.role_name not in roles:
            raise forbidden()
        return user

    return guard