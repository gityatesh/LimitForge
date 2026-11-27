"""Test setup: a real PostgreSQL test database, wiped clean before every test."""
import os

# Must be set BEFORE the app is imported, so the app connects to the TEST database
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://finora:finora_dev_password@localhost:5433/finora_test")
os.environ["JWT_SECRET"] = "test-secret"

import functools  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import scripts.seed as seed_module  # noqa: E402
from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import workflow  # noqa: E402
from app.services.clients import BureauResponse, LimitForgeResponse, ServiceError  # noqa: E402

# Argon2 is slow on purpose; cache the demo hashes so tests stay fast
seed_module.hash_password = functools.lru_cache(maxsize=None)(seed_module.hash_password)

PASSWORDS = {email: pw for _, email, pw, _ in seed_module.DEMO_USERS}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with SessionLocal() as db:
        seed_module.ensure_base(db)
        db.commit()
    reset_rate_limits()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def login(client, email, password=None):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password or PASSWORDS[email]})
    assert r.status_code == 200, r.text
    client.cookies.clear()      # tests authenticate with the Bearer header only
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def h(client):
    """Ready-made auth headers for each demo role."""
    headers = {
        "customer": login(client, "customer@finora.dev"),
        "analyst": login(client, "analyst@finora.dev"),
        "manager": login(client, "manager@finora.dev"),
        "manager2": login(client, "manager2@finora.dev"),
        "admin": login(client, "admin@finora.dev"),
    }
    reset_rate_limits()         # these set-up logins should not count against the test
    return headers



# ---------------------------------------------------------------- fake external services
class FakeServices:
    """Stands in for LimitForge + the bureau so tests never need the real services (NFR-12).
    Each test can change the behaviour, e.g. fake.risk = 0.9 or fake.bureau_mode = "error"."""

    def __init__(self):
        self.ai_mode = "ok"
        self.bureau_mode = "ok"
        self.risk = 0.10
        self.recommended_ratio = 1.0        # recommended limit = requested * ratio
        self.bureau_score = 760
        self.ai_calls = 0
        self.bureau_calls = 0

    def limitforge(self, req):
        self.ai_calls += 1
        if self.ai_mode == "error":
            raise ServiceError("LimitForge returned HTTP 503")
        rec = round(req.requested_credit_limit * self.recommended_ratio)
        cat = "HIGH" if self.risk >= 0.65 else "MEDIUM" if self.risk >= 0.30 else "LOW"
        label = "DECLINE" if cat == "HIGH" else (
            "APPROVE_WITHIN_LIMIT" if rec >= req.requested_credit_limit else "APPROVE_REDUCED_LIMIT")
        return LimitForgeResponse(
            model_name="fake-limitforge", model_version="test", spending_forecast=12345.0, risk_score=self.risk,
            risk_category=cat, recommended_credit_limit=0 if label == "DECLINE" else rec, recommendation=label,
            reason_codes=[{"code": "HIGH_DEBT_TO_INCOME", "label": "Existing debt is high", "impact": 0.2}])

    def bureau(self, req):
        self.bureau_calls += 1
        if self.bureau_mode == "error":
            raise ServiceError("Credit bureau returned HTTP 503")
        s = self.bureau_score
        band = ("NO_HISTORY" if s is None else "EXCELLENT" if s >= 750 else "GOOD" if s >= 700
                else "FAIR" if s >= 650 else "POOR")
        return BureauResponse(provider="FakeBureau", customer_reference=req.customer_reference, bureau_score=s,
                              score_band=band, active_accounts=2, delinquencies_24m=0, enquiries_6m=1)


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    f = FakeServices()
    monkeypatch.setattr(workflow, "call_limitforge", f.limitforge)
    monkeypatch.setattr(workflow, "call_bureau", f.bureau)
    return f


def submit(client, headers, amount=30_000, purpose="Laptop purchase"):
    r = client.post("/api/v1/applications", json={"requested_credit_limit": amount, "application_purpose": purpose},
                    headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["application_id"]


def new_customer(client, email="other@finora.dev", complete=True):
    r = client.post("/api/v1/auth/register", json={"full_name": "Other Person", "email": email,
                                                    "password": "Password1"})
    assert r.status_code == 201, r.text
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    if complete:
        client.put("/api/v1/profile/me", headers=headers, json={
            "annual_income": 800000, "monthly_expenses": 25000, "existing_debt": 50000,
            "employment_status": "SALARIED", "credit_history_months": 48})
    return headers