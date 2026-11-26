"""LimitForge contract + behaviour tests. Run `python train.py` once first."""
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
BASE = {"application_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "requested_credit_limit": 150000.0,
        "annual_income": 1200000.0, "monthly_expenses": 35000.0, "existing_debt": 100000.0,
        "employment_status": "SALARIED", "credit_history_months": 36}
RISKY = {**BASE, "requested_credit_limit": 100000, "annual_income": 150000, "monthly_expenses": 10000,
         "existing_debt": 140000, "employment_status": "UNEMPLOYED", "credit_history_months": 0}
KEYS = {"model_name", "model_version", "spending_forecast", "risk_score", "risk_category",
        "recommended_credit_limit", "recommendation", "reason_codes"}


def test_response_matches_contract():
    body = c.post("/internal/v1/assess", json=BASE).json()
    assert set(body) == KEYS
    assert 0 <= body["risk_score"] <= 1
    assert body["recommended_credit_limit"] <= BASE["requested_credit_limit"]


def test_risky_profile_declined_with_reasons():
    body = c.post("/internal/v1/assess", json=RISKY).json()
    assert body["risk_category"] == "HIGH" and body["recommendation"] == "DECLINE"
    assert body["recommended_credit_limit"] == 0
    codes = [r["code"] for r in body["reason_codes"]]
    assert 1 <= len(codes) <= 3 and "HIGH_DEBT_TO_INCOME" in codes
    impacts = [r["impact"] for r in body["reason_codes"]]
    assert impacts == sorted(impacts, reverse=True)          # biggest reason first


def test_more_debt_never_lowers_risk():
    low = c.post("/internal/v1/assess", json={**BASE, "existing_debt": 0}).json()["risk_score"]
    high = c.post("/internal/v1/assess", json={**BASE, "existing_debt": 900000}).json()["risk_score"]
    assert high > low


def test_same_input_same_output():
    assert c.post("/internal/v1/assess", json=BASE).json() == c.post("/internal/v1/assess", json=BASE).json()


def test_invalid_input_rejected():
    assert c.post("/internal/v1/assess", json={**BASE, "requested_credit_limit": -1}).status_code == 422
    assert c.post("/internal/v1/assess", json={**BASE, "employment_status": "PIRATE"}).status_code == 422


def test_fault_injection_modes():
    c.post("/internal/v1/fault", json={"mode": "error"})
    assert c.post("/internal/v1/assess", json=BASE).status_code == 503
    c.post("/internal/v1/fault", json={"mode": "invalid"})
    assert "recommendation" not in c.post("/internal/v1/assess", json=BASE).json()
    c.post("/internal/v1/fault", json={"mode": "none"})
    assert c.post("/internal/v1/assess", json=BASE).status_code == 200