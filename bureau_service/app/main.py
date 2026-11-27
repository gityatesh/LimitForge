"""Mock credit bureau (fake CIBIL), feature 2.  Contract: POST /v1/credit-report

SYNTHETIC ONLY. A real bureau looks the person up by PAN in its own records.
We have no records, so we GENERATE a believable report:
  * deterministic: the same customer_reference always gets the same report (seeded random)
  * correlated with the profile: more debt / shorter history -> worse score
Fault injection (demo failure handling):  POST /v1/fault {"mode": "error"}
"""
import hashlib
import os
import random
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

PROVIDER = "FinoraMockBureau"
app = FastAPI(title="Finora Mock Credit Bureau", version="1.0.0")
_fault_mode = os.getenv("BUREAU_FAULT_MODE", "none")


class ReportRequest(BaseModel):
    customer_reference: str = Field(min_length=3, max_length=32)
    annual_income: float = Field(ge=0)
    existing_debt: float = Field(ge=0)
    employment_status: Literal["SALARIED", "SELF_EMPLOYED", "STUDENT", "UNEMPLOYED"]
    credit_history_months: int = Field(ge=0, le=1200)


class ReportResponse(BaseModel):
    provider: str
    customer_reference: str
    bureau_score: int | None          # 300..900, None = no credit history ("NH" in CIBIL terms)
    score_band: Literal["EXCELLENT", "GOOD", "FAIR", "POOR", "NO_HISTORY"]
    active_accounts: int
    delinquencies_24m: int            # missed payments in the last 24 months
    enquiries_6m: int                 # credit applications in the last 6 months


class FaultRequest(BaseModel):
    mode: Literal["none", "timeout", "error"]


def band(score: int | None) -> str:
    if score is None:
        return "NO_HISTORY"
    if score >= 750:
        return "EXCELLENT"
    if score >= 700:
        return "GOOD"
    if score >= 650:
        return "FAIR"
    return "POOR"


def generate_report(req: ReportRequest) -> ReportResponse:
    # Same customer -> same seed -> same "random" numbers every time
    seed = int(hashlib.sha256(req.customer_reference.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)

    if req.credit_history_months < 6:      # too new to have a score
        return ReportResponse(provider=PROVIDER, customer_reference=req.customer_reference, bureau_score=None,
                              score_band="NO_HISTORY", active_accounts=0, delinquencies_24m=0,
                              enquiries_6m=rng.randint(0, 2))

    dti = req.existing_debt / max(req.annual_income, 1)
    active = max(0, min(12, int(dti * 6) + rng.randint(0, 3)))
    delinquencies = max(0, int(rng.gauss(dti * 3, 1)))
    enquiries = rng.randint(0, 4)
    emp_adj = {"SALARIED": 25, "SELF_EMPLOYED": 5, "STUDENT": -20, "UNEMPLOYED": -60}[req.employment_status]

    score = (720
             + min(req.credit_history_months, 120) * 0.6      # longer history helps (max +72)
             - dti * 120                                      # more debt hurts
             - delinquencies * 45                             # missed payments hurt a lot
             - enquiries * 8                                  # many recent applications hurt a little
             + emp_adj
             + rng.randint(-25, 25))                          # individual variation
    score = int(max(300, min(900, score)))
    return ReportResponse(provider=PROVIDER, customer_reference=req.customer_reference, bureau_score=score,
                          score_band=band(score), active_accounts=active, delinquencies_24m=delinquencies,
                          enquiries_6m=enquiries)


@app.get("/health")
def health():
    return {"status": "ok", "provider": PROVIDER, "fault_mode": _fault_mode}


@app.post("/v1/fault")
def set_fault(req: FaultRequest):
    global _fault_mode
    _fault_mode = req.mode
    return {"fault_mode": _fault_mode}


@app.post("/v1/credit-report", response_model=ReportResponse)
def credit_report(req: ReportRequest):
    if _fault_mode == "timeout":
        time.sleep(30)
    if _fault_mode == "error":
        raise HTTPException(status_code=503, detail="Bureau unavailable (injected fault)")
    return generate_report(req)