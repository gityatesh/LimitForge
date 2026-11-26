"""LimitForge recommendation service. Contract: POST /internal/v1/assess
Outputs are ADVISORY. Finora never auto-approves from them (BR-03).

Fault injection (to demo failure handling live):  POST /internal/v1/fault {"mode": "error"}
"""
import os
import time
from typing import Literal
from uuid import UUID

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.features import REASON_GROUPS, build_features

MODEL_PATH = os.getenv("LIMITFORGE_MODEL_PATH", "models/limitforge.joblib")
HIGH_RISK, MEDIUM_RISK = 0.65, 0.30
MIN_REASON_IMPACT = 0.01   # ignore factors that move the risk by less than 1 point

app = FastAPI(title="LimitForge Recommendation Service", version="2.0.0")
_bundle = None
_fault_mode = os.getenv("LIMITFORGE_FAULT_MODE", "none")


def bundle():
    global _bundle
    if _bundle is None:
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


class AssessRequest(BaseModel):
    application_id: UUID
    requested_credit_limit: float = Field(gt=0)
    annual_income: float = Field(ge=0)
    monthly_expenses: float = Field(ge=0)
    existing_debt: float = Field(ge=0)
    employment_status: Literal["SALARIED", "SELF_EMPLOYED", "STUDENT", "UNEMPLOYED"]
    credit_history_months: int = Field(ge=0, le=1200)


class ReasonCode(BaseModel):
    code: str
    label: str
    impact: float   # how much this factor adds to the risk score (0..1)


class AssessResponse(BaseModel):
    model_name: str
    model_version: str
    spending_forecast: float
    risk_score: float
    risk_category: Literal["LOW", "MEDIUM", "HIGH"]
    recommended_credit_limit: float
    recommendation: Literal["APPROVE_WITHIN_LIMIT", "APPROVE_REDUCED_LIMIT", "DECLINE"]
    reason_codes: list[ReasonCode]


class FaultRequest(BaseModel):
    mode: Literal["none", "timeout", "error", "invalid"]


def explain(x: np.ndarray, risk: float) -> list[ReasonCode]:
    """Reason codes by substitution: swap ONE factor for the typical low-risk applicant's value and
    see how much the risk drops. The bigger the drop, the more that factor is to blame.
    This is an approximate, model-agnostic explanation (not exact model internals)."""
    b = bundle()
    reasons = []
    for code, (cols, label) in REASON_GROUPS.items():
        x_alt = x.copy()
        x_alt[cols] = b["reference"][cols]
        impact = risk - float(b["risk_model"].predict_proba(x_alt.reshape(1, -1))[0, 1])
        if impact >= MIN_REASON_IMPACT:
            reasons.append(ReasonCode(code=code, label=label, impact=round(impact, 4)))
    return sorted(reasons, key=lambda r: r.impact, reverse=True)[:3]


def assess_core(req: AssessRequest) -> AssessResponse:
    b = bundle()
    x = build_features(req.requested_credit_limit, req.annual_income, req.monthly_expenses,
                       req.existing_debt, req.employment_status, req.credit_history_months)
    risk = float(b["risk_model"].predict_proba(x.reshape(1, -1))[0, 1])
    spend = max(float(b["spend_model"].predict(x.reshape(1, -1))[0]), 0.0)

    category = "HIGH" if risk >= HIGH_RISK else "MEDIUM" if risk >= MEDIUM_RISK else "LOW"
    # Recommended limit = 6 months of risk-adjusted spare money, never more than requested
    monthly_surplus = max(req.annual_income / 12 - req.monthly_expenses, 0)
    recommended = round(min(req.requested_credit_limit, monthly_surplus * 6 * (1 - risk)) / 1000) * 1000

    if category == "HIGH" or recommended < 1000:
        recommendation, recommended = "DECLINE", 0.0
    elif recommended >= req.requested_credit_limit:
        recommendation = "APPROVE_WITHIN_LIMIT"
    else:
        recommendation = "APPROVE_REDUCED_LIMIT"

    return AssessResponse(
        model_name=b["model_name"], model_version=b["model_version"], spending_forecast=round(spend, 2),
        risk_score=round(risk, 4), risk_category=category, recommended_credit_limit=float(recommended),
        recommendation=recommendation, reason_codes=explain(x, risk),
    )


@app.get("/health")
def health():
    b = bundle()
    return {"status": "ok", "model_version": b["model_version"], "metrics": b["metrics"], "fault_mode": _fault_mode}


@app.post("/internal/v1/fault")
def set_fault(req: FaultRequest):
    global _fault_mode
    _fault_mode = req.mode
    return {"fault_mode": _fault_mode}


@app.post("/internal/v1/assess", response_model=None)
def assess(req: AssessRequest):
    if _fault_mode == "timeout":
        time.sleep(30)
    if _fault_mode == "error":
        raise HTTPException(status_code=503, detail="LimitForge unavailable (injected fault)")
    if _fault_mode == "invalid":
        return {"model_name": "limitforge-ensemble", "risk_score": "not-a-number"}
    return assess_core(req)