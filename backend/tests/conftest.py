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