"""Mock bureau tests."""
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
GOOD = {"customer_reference": "CUST-GOOD0001", "annual_income": 1200000, "existing_debt": 50000,
        "employment_status": "SALARIED", "credit_history_months": 96}
BAD = {"customer_reference": "CUST-BAD00001", "annual_income": 150000, "existing_debt": 300000,
       "employment_status": "UNEMPLOYED", "credit_history_months": 24}


def report(body):
    r = c.post("/v1/credit-report", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_score_in_range_and_band_matches():
    for body in (GOOD, BAD):
        r = report(body)
        assert 300 <= r["bureau_score"] <= 900
        s = r["bureau_score"]
        expected = "EXCELLENT" if s >= 750 else "GOOD" if s >= 700 else "FAIR" if s >= 650 else "POOR"
        assert r["score_band"] == expected


def test_same_customer_same_report():
    assert report(GOOD) == report(GOOD)


def test_good_profile_scores_higher_than_bad():
    assert report(GOOD)["bureau_score"] > report(BAD)["bureau_score"]
    assert report(BAD)["score_band"] == "POOR"


def test_new_customer_has_no_history():
    r = report({**GOOD, "customer_reference": "CUST-NEW00001", "credit_history_months": 2})
    assert r["bureau_score"] is None and r["score_band"] == "NO_HISTORY"


def test_invalid_input_rejected():
    assert c.post("/v1/credit-report", json={**GOOD, "employment_status": "PIRATE"}).status_code == 422


def test_fault_injection():
    c.post("/v1/fault", json={"mode": "error"})
    assert c.post("/v1/credit-report", json=GOOD).status_code == 503
    c.post("/v1/fault", json={"mode": "none"})
    assert c.post("/v1/credit-report", json=GOOD).status_code == 200