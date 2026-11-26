"""Input validation for auth + admin endpoints (NFR-06)."""
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

RoleLiteral = Literal["CUSTOMER", "ANALYST", "MANAGER", "ADMIN"]


def _strong_enough(pw: str) -> str:
    if not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        raise ValueError("Password must contain at least one letter and one number")
    return pw


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    _name = field_validator("full_name")(lambda v: v.strip())
    _pw = field_validator("password")(_strong_enough)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AdminUserCreateIn(RegisterIn):
    role: RoleLiteral


class RoleChangeIn(BaseModel):
    role: RoleLiteral


class StatusChangeIn(BaseModel):
    account_status: Literal["ACTIVE", "DISABLED"]