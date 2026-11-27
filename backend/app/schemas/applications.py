"""Input validation for applications (FR-06, FR-07)."""
from pydantic import BaseModel, Field, field_validator

MIN_LIMIT = 1_000
MAX_LIMIT = 10_000_000


class DraftIn(BaseModel):
    """Relaxed: a draft may be incomplete (FR-06)."""
    requested_credit_limit: float | None = Field(default=None, ge=0, le=MAX_LIMIT)
    application_purpose: str | None = Field(default=None, max_length=200)


class SubmitIn(BaseModel):
    """Strict: everything must be valid before submission (FR-07)."""
    requested_credit_limit: float = Field(ge=MIN_LIMIT, le=MAX_LIMIT)
    application_purpose: str = Field(min_length=3, max_length=200)

    _strip = field_validator("application_purpose")(lambda v: v.strip())