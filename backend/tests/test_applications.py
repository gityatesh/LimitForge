"""Step 7 API tests: drafts, strict submission, assessment + bureau, failures, withdrawal, views, lists."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Alert, AuditEvent
from tests.conftest import new_customer, submit

API = "/api/v1"


def test_draft_is_relaxed_private_and_not_assessed(client, h, fake):
    r = client.post(f"{API}/applications/draft", headers=h["customer"], json={})
    assert r.status_code == 201 and r.json()["application_status"] == "DRAFT"
    assert fake.ai_calls == 0 and fake.bureau_calls == 0
    assert client.get(f"{API}/applications/{r.json()['application_id']}", headers=h["manager"]).status_code == 404


def test_draft_submit_uses_strict_rules(client, h):
    d = client.post(f"{API}/applications/draft", headers=h["customer"], json={"requested_credit_limit": 500}).json()
    r = client.post(f"{API}/applications/{d['application_id']}/submit", headers=h["customer"])
    assert r.status_code == 422 and {x["field"] for x in r.json()["details"]} == {
        "requested_credit_limit", "application_purpose"}
    client.put(f"{API}/applications/{d['application_id']}", headers=h["customer"],
               json={"requested_credit_limit": 40000, "application_purpose": "Travel"})
    r = client.post(f"{API}/applications/{d['application_id']}/submit", headers=h["customer"])
    assert r.status_code == 200 and r.json()["application_status"] == "SUBMITTED"


def test_invalid_new_submission_rejected(client, h):
    for body in ({"requested_credit_limit": 10, "application_purpose": "x y z"},
                 {"requested_credit_limit": 50_000_000, "application_purpose": "Travel"},
                 {"requested_credit_limit": 20000, "application_purpose": "  "}):
        assert client.post(f"{API}/applications", headers=h["customer"], json=body).status_code == 422


def test_incomplete_profile_blocks_submission(client):
    headers = new_customer(client, complete=False)
    r = client.post(f"{API}/applications", headers=headers,
                    json={"requested_credit_limit": 20000, "application_purpose": "Travel"})
    assert r.json()["error_code"] == "PROFILE_INCOMPLETE"


def test_submission_pulls_bureau_and_ai_in_one_go(client, h, fake):
    app_id = submit(client, h["customer"])
    assert fake.ai_calls == 1 and fake.bureau_calls == 1
    d = client.get(f"{API}/applications/{app_id}", headers=h["manager"]).json()
    assert d["application_status"] == "SUBMITTED"                       # never auto-approved (BR-03)
    assert d["latest_assessment"]["label"] == "Advisory Model Recommendation"
    assert d["latest_assessment"]["reason_codes"][0]["code"] == "HIGH_DEBT_TO_INCOME"
    assert d["latest_assessment"]["rule_version_number"] == 1
    assert d["latest_bureau_report"]["bureau_score"] == 760
    assert d["routing"]["analyst_can_decide"] is True


def test_low_bureau_score_escalates(client, h, fake):
    fake.bureau_score = 610
    d = client.get(f"{API}/applications/{submit(client, h['customer'])}", headers=h["manager"]).json()
    assert d["routing"]["escalation_required"] and d["routing"]["bureau_breach"]


def test_service_failures_are_recorded_never_approved(client, h, fake):
    fake.ai_mode = "error"
    fake.bureau_mode = "error"
    app_id = submit(client, h["customer"])
    d = client.get(f"{API}/applications/{app_id}", headers=h["manager"]).json()
    assert d["application_status"] == "SUBMITTED"
    assert d["latest_assessment"]["assessment_status"] == "FAILED"
    assert d["latest_bureau_report"]["report_status"] == "FAILED"
    assert d["routing"]["analyst_can_decide"] is False
    with SessionLocal() as db:
        types = {a.alert_type for a in db.scalars(select(Alert)).all()}
        assert {"ASSESSMENT_FAILED", "BUREAU_FAILED"} <= types
        events = {e.event_type for e in db.scalars(select(AuditEvent)).all()}
        assert {"ASSESSMENT_FAILED", "BUREAU_FAILED"} <= events


def test_customer_view_hides_internal_data(client, h):
    app_id = submit(client, h["customer"])
    text = str(client.get(f"{API}/applications/{app_id}", headers=h["customer"]).json())
    for hidden in ("risk_score", "bureau_score", "reason_codes", "routing", "review_notes", "decision_reason"):
        assert hidden not in text


def test_customers_cannot_see_each_other(client, h):
    app_id = submit(client, h["customer"])
    other = new_customer(client)
    assert client.get(f"{API}/applications/{app_id}", headers=other).status_code == 404
    assert client.post(f"{API}/applications/{app_id}/withdraw", headers=other).status_code == 404
    assert client.get(f"{API}/applications", headers=other).json()["total"] == 0


def test_withdrawal_rules(client, h):
    app_id = submit(client, h["customer"])
    assert client.post(f"{API}/applications/{app_id}/withdraw", headers=h["customer"]).json()[
        "application_status"] == "WITHDRAWN"
    assert client.post(f"{API}/applications/{app_id}/withdraw", headers=h["customer"]).status_code == 409


def test_withdrawal_after_submit_respects_rule(client, h):
    rule = client.get(f"{API}/rules", headers=h["admin"]).json()[0]
    cfg = {**rule["latest_version"]["rule_configuration"], "allow_withdrawal_submitted": False}
    client.put(f"{API}/rules/{rule['rule_id']}", headers=h["admin"], json={"rule_configuration": cfg})
    app_id = submit(client, h["customer"])
    r = client.post(f"{API}/applications/{app_id}/withdraw", headers=h["customer"])
    assert r.status_code == 409 and r.json()["error_code"] == "WITHDRAWAL_NOT_PERMITTED"


def test_lists_filters_and_pagination(client, h, fake):
    for amount in (20000, 25000, 30000):
        submit(client, h["customer"], amount)
    fake.risk = 0.8
    high = submit(client, h["customer"], 40000)
    page = client.get(f"{API}/applications?page_size=2", headers=h["manager"]).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    only_high = client.get(f"{API}/applications?risk_category=HIGH", headers=h["analyst"]).json()
    assert [i["application_id"] for i in only_high["items"]] == [high]
    mine = client.get(f"{API}/applications", headers=h["customer"]).json()
    assert mine["total"] == 4 and "risk_score" not in mine["items"][0]


def test_admin_cannot_view_application_but_can_view_its_audit(client, h):
    app_id = submit(client, h["customer"])
    assert client.get(f"{API}/applications/{app_id}", headers=h["admin"]).status_code == 403
    trail = client.get(f"{API}/applications/{app_id}/audit", headers=h["admin"]).json()
    assert [e["event_type"] for e in trail][:1] == ["APPLICATION_SUBMITTED"]
    assert trail[0]["previous_state"] is None and trail[0]["new_state"] == "SUBMITTED"


def test_analyst_cannot_see_audit_of_case_they_never_touched(client, h):
    app_id = submit(client, h["customer"])
    assert client.get(f"{API}/applications/{app_id}/audit", headers=h["analyst"]).status_code == 403