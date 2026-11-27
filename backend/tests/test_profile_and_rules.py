"""Step 6 tests: profile (FR-05), statement upload (feature 10), service clients, rules (FR-23..26)."""
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.services import clients
from app.services.clients import BureauRequest, LimitForgeRequest, ServiceError

API = "/api/v1"
SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "sample_statement.csv"
PROFILE = {"annual_income": 900000, "monthly_expenses": 30000, "existing_debt": 50000,
           "employment_status": "SELF_EMPLOYED", "credit_history_months": 24}


# ---------------- profile ----------------
def test_customer_reads_and_updates_profile(client, h):
    assert client.get(f"{API}/profile/me", headers=h["customer"]).json()["is_complete"] is True
    r = client.put(f"{API}/profile/me", headers=h["customer"], json=PROFILE)
    assert r.status_code == 200 and r.json()["employment_status"] == "SELF_EMPLOYED"
    assert r.json()["income_source"] == "MANUAL"


def test_profile_validation_errors_are_per_field(client, h):
    r = client.put(f"{API}/profile/me", headers=h["customer"],
                   json={**PROFILE, "annual_income": -1, "employment_status": "ASTRONAUT"})
    assert r.status_code == 422
    assert {"annual_income", "employment_status"} <= {d["field"] for d in r.json()["details"]}


def test_only_customers_have_a_profile(client, h):
    for role in ("analyst", "manager", "admin"):
        assert client.get(f"{API}/profile/me", headers=h[role]).status_code == 403


def test_register_creates_empty_incomplete_profile(client):
    r = client.post(f"{API}/auth/register", json={"full_name": "New Person", "email": "n@finora.dev",
                                                  "password": "Password1"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{API}/profile/me", headers=headers).json()["is_complete"] is False


# ---------------- statement upload ----------------
def test_statement_upload_fills_profile(client, h):
    with open(SAMPLE, "rb") as f:
        r = client.post(f"{API}/profile/me/statement", headers=h["customer"],
                        files={"file": ("statement.csv", f, "text/csv")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["statement"]["months_covered"] == 3
    assert body["statement"]["avg_monthly_income"] == 99000.0          # (95k*3 + 12k) / 3
    assert body["profile"]["annual_income"] == 1188000.0
    assert body["profile"]["income_source"] == "STATEMENT"
    assert len(client.get(f"{API}/profile/me/statements", headers=h["customer"]).json()) == 1
    # typing numbers again switches the source back to MANUAL
    r = client.put(f"{API}/profile/me", headers=h["customer"], json=PROFILE)
    assert r.json()["income_source"] == "MANUAL" and r.json()["statement_verified"] is False


def test_bad_statement_rejected(client, h):
    r = client.post(f"{API}/profile/me/statement", headers=h["customer"],
                    files={"file": ("x.csv", b"date,amount\n2026-01-01,5", "text/csv")})
    assert r.status_code == 422 and r.json()["error_code"] == "INVALID_STATEMENT"
    r = client.post(f"{API}/profile/me/statement", headers=h["customer"],
                    files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.json()["error_code"] == "INVALID_FILE_TYPE"


# ---------------- service clients (no network: httpx.post is faked) ----------------
LF_REQ = LimitForgeRequest(application_id="x", requested_credit_limit=1, annual_income=1, monthly_expenses=1,
                           existing_debt=0, employment_status="SALARIED", credit_history_months=1)
BU_REQ = BureauRequest(customer_reference="CUST-1", annual_income=1, existing_debt=0,
                       employment_status="SALARIED", credit_history_months=1)


def fake_post(monkeypatch, fn):
    monkeypatch.setattr(clients.httpx, "post", fn)


def test_limitforge_client_parses_good_response(monkeypatch):
    good = {"model_name": "m", "model_version": "1", "spending_forecast": 10, "risk_score": 0.2,
            "risk_category": "LOW", "recommended_credit_limit": 1000, "recommendation": "APPROVE_WITHIN_LIMIT",
            "reason_codes": [{"code": "X", "label": "x", "impact": 0.1}]}
    fake_post(monkeypatch, lambda *a, **k: httpx.Response(200, json=good))
    assert clients.call_limitforge(LF_REQ).reason_codes[0].code == "X"


@pytest.mark.parametrize("behaviour,message", [
    ("timeout", "timed out"), ("503", "HTTP 503"), ("garbage", "schema"),
])
def test_clients_turn_every_failure_into_service_error(monkeypatch, behaviour, message):
    def post(*a, **k):
        if behaviour == "timeout":
            raise httpx.ReadTimeout("slow")
        if behaviour == "503":
            return httpx.Response(503)
        return httpx.Response(200, json={"risk_score": "nope"})
    fake_post(monkeypatch, post)
    for call, req in ((clients.call_limitforge, LF_REQ), (clients.call_bureau, BU_REQ)):
        with pytest.raises(ServiceError, match=message):
            call(req)


def test_client_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "bureau_url", "http://127.0.0.1:9")
    with pytest.raises(ServiceError, match="unreachable"):
        clients.call_bureau(BU_REQ)


# ---------------- rules ----------------
def _rule(client, h):
    return client.get(f"{API}/rules", headers=h["admin"]).json()[0]


def test_default_rule_is_seeded_and_readable_by_staff(client, h):
    for role in ("analyst", "manager", "admin"):
        r = client.get(f"{API}/rules/active", headers=h[role]).json()
        assert r["rule_name"] == "standard_credit_policy" and r["version_number"] == 1
    assert client.get(f"{API}/rules/active", headers=h["customer"]).status_code == 403


def test_saving_a_rule_creates_a_new_immutable_version(client, h):
    rule = _rule(client, h)
    cfg = {**rule["latest_version"]["rule_configuration"], "min_bureau_score": 700}
    r = client.put(f"{API}/rules/{rule['rule_id']}", headers=h["admin"], json={"rule_configuration": cfg})
    assert r.json()["latest_version"]["version_number"] == 2
    versions = client.get(f"{API}/rules/{rule['rule_id']}/versions", headers=h["admin"]).json()
    assert [v["rule_configuration"]["min_bureau_score"] for v in versions] == [700, 650]
    # saving the identical config again is refused
    assert client.put(f"{API}/rules/{rule['rule_id']}", headers=h["admin"],
                      json={"rule_configuration": cfg}).status_code == 409


@pytest.mark.parametrize("change", [
    {"max_auto_approval_limit": 999999},          # above escalation limit
    {"high_risk_score_threshold": 1.5},
    {"min_bureau_score": 100},
    {"dual_approval_override_limit": 10},         # below the analyst ceiling
    {"sla_pending_hours": 0},
])
def test_contradictory_rules_rejected(client, h, change):
    rule = _rule(client, h)
    cfg = {**rule["latest_version"]["rule_configuration"], **change}
    r = client.put(f"{API}/rules/{rule['rule_id']}", headers=h["admin"], json={"rule_configuration": cfg})
    assert r.status_code == 422 and r.json()["error_code"] == "INVALID_RULE_CONFIGURATION"


def test_only_one_rule_active(client, h):
    first = _rule(client, h)
    second = client.post(f"{API}/rules", headers=h["admin"], json={
        "rule_name": "strict_policy", "rule_configuration": first["latest_version"]["rule_configuration"]}).json()
    assert second["is_active"] is False
    client.patch(f"{API}/rules/{second['rule_id']}/activate", headers=h["admin"])
    active = {r["rule_name"]: r["is_active"] for r in client.get(f"{API}/rules", headers=h["admin"]).json()}
    assert active == {"standard_credit_policy": False, "strict_policy": True}
    assert client.get(f"{API}/rules/active", headers=h["manager"]).json()["rule_name"] == "strict_policy"


def test_rules_admin_only(client, h):
    for role in ("customer", "analyst", "manager"):
        assert client.get(f"{API}/rules", headers=h[role]).status_code == 403