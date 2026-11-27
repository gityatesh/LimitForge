"""HTTP clients for the two external services (FR-11, FR-14, feature 2).

Any timeout, connection error, HTTP error or wrong-shaped answer raises ServiceError.
The caller then records a FAILED result. A failure NEVER means approval (BR-09).
"""
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import settings


class ServiceError(Exception):
    pass


# ---------- LimitForge (AI) ----------
class LimitForgeRequest(BaseModel):
    application_id: str
    requested_credit_limit: float
    annual_income: float
    monthly_expenses: float
    existing_debt: float
    employment_status: str
    credit_history_months: int


class ReasonCode(BaseModel):
    code: str
    label: str
    impact: float


class LimitForgeResponse(BaseModel):
    model_name: str
    model_version: str
    spending_forecast: float = Field(ge=0)
    risk_score: float = Field(ge=0, le=1)
    risk_category: Literal["LOW", "MEDIUM", "HIGH"]
    recommended_credit_limit: float = Field(ge=0)
    recommendation: Literal["APPROVE_WITHIN_LIMIT", "APPROVE_REDUCED_LIMIT", "DECLINE"]
    reason_codes: list[ReasonCode] = []


# ---------- Credit bureau ----------
class BureauRequest(BaseModel):
    customer_reference: str
    annual_income: float
    existing_debt: float
    employment_status: str
    credit_history_months: int


class BureauResponse(BaseModel):
    provider: str
    customer_reference: str
    bureau_score: int | None = Field(default=None, ge=300, le=900)
    score_band: Literal["EXCELLENT", "GOOD", "FAIR", "POOR", "NO_HISTORY"]
    active_accounts: int = Field(ge=0)
    delinquencies_24m: int = Field(ge=0)
    enquiries_6m: int = Field(ge=0)


def _post(name: str, url: str, payload: BaseModel, response_model: type[BaseModel]):
    """Shared call logic: POST JSON, enforce timeout, validate the answer's shape."""
    try:
        resp = httpx.post(url, json=payload.model_dump(), timeout=settings.service_timeout_seconds)
    except httpx.TimeoutException:
        raise ServiceError(f"{name} timed out after {settings.service_timeout_seconds}s")
    except httpx.HTTPError as exc:
        raise ServiceError(f"{name} unreachable ({type(exc).__name__})")
    if resp.status_code >= 400:
        raise ServiceError(f"{name} returned HTTP {resp.status_code}")
    try:
        return response_model.model_validate(resp.json())
    except (ValidationError, ValueError):
        raise ServiceError(f"{name} response failed schema validation")


def call_limitforge(payload: LimitForgeRequest) -> LimitForgeResponse:
    return _post("LimitForge", f"{settings.limitforge_url.rstrip('/')}/internal/v1/assess",
                 payload, LimitForgeResponse)


def call_bureau(payload: BureauRequest) -> BureauResponse:
    return _post("Credit bureau", f"{settings.bureau_url.rstrip('/')}/v1/credit-report",
                 payload, BureauResponse)