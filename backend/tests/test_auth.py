"""Step 3 tests: FR-01, FR-03, NFR-04/05, features 4 (hash chain) and 5 (lockout, rate limit)."""
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import AuditEvent, User
from app.services.audit import verify_chain
from tests.conftest import login

API = "/api/v1"


def test_register_defaults_to_customer(client):
    r = client.post(f"{API}/auth/register", json={"full_name": "New Person", "email": "New@Finora.dev",
                                                  "password": "Password1"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "CUSTOMER"
    dup = client.post(f"{API}/auth/register", json={"full_name": "Dup", "email": "new@finora.dev",
                                                    "password": "Password1"})
    assert dup.status_code == 409


def test_weak_password_rejected(client):
    r = client.post(f"{API}/auth/register", json={"full_name": "Weak", "email": "w@finora.dev", "password": "abcdefgh"})
    assert r.status_code == 422 and r.json()["details"][0]["field"] == "password"


def test_login_errors_are_generic(client):
    wrong = client.post(f"{API}/auth/login", json={"email": "customer@finora.dev", "password": "nope"})
    ghost = client.post(f"{API}/auth/login", json={"email": "ghost@finora.dev", "password": "nope"})
    assert wrong.status_code == ghost.status_code == 401
    assert wrong.json()["message"] == ghost.json()["message"]


def test_lockout_after_five_failures_and_admin_unlock(client, h):
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": "analyst@finora.dev", "password": "bad"})
    r = client.post(f"{API}/auth/login", json={"email": "analyst@finora.dev", "password": "Analyst@123"})
    assert r.status_code == 403 and r.json()["error_code"] == "ACCOUNT_LOCKED"   # even the right password

    users = client.get(f"{API}/admin/users?q=analyst@", headers=h["admin"]).json()
    target = next(u for u in users if u["email"] == "analyst@finora.dev")
    assert target["is_locked"] is True
    client.post(f"{API}/admin/users/{target['user_id']}/unlock", headers=h["admin"])
    assert client.post(f"{API}/auth/login", json={"email": "analyst@finora.dev",
                                                  "password": "Analyst@123"}).status_code == 200


def test_rate_limit_on_login(client):
    codes = [client.post(f"{API}/auth/login", json={"email": "x@finora.dev", "password": "x"}).status_code
             for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_me_requires_valid_token(client, h):
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get(f"{API}/auth/me", headers=h["manager"]).json()["role"] == "MANAGER"


def test_admin_creates_user_changes_role_and_disables(client, h):
    r = client.post(f"{API}/admin/users", headers=h["admin"], json={
        "full_name": "Temp Manager", "email": "temp@finora.dev", "password": "Password1", "role": "MANAGER"})
    uid = r.json()["user_id"]
    token = login(client, "temp@finora.dev", "Password1")
    assert client.patch(f"{API}/admin/users/{uid}/role", headers=h["admin"],
                        json={"role": "ANALYST"}).json()["role"] == "ANALYST"
    client.patch(f"{API}/admin/users/{uid}/status", headers=h["admin"], json={"account_status": "DISABLED"})
    r = client.get(f"{API}/auth/me", headers=token)          # old token stops working immediately
    assert r.status_code == 403 and r.json()["error_code"] == "ACCOUNT_DISABLED"


def test_admin_cannot_modify_self(client, h):
    me = client.get(f"{API}/auth/me", headers=h["admin"]).json()
    r = client.patch(f"{API}/admin/users/{me['user_id']}/status", headers=h["admin"], json={"account_status": "DISABLED"})
    assert r.status_code == 409


def test_rbac_admin_endpoints_blocked_for_other_roles(client, h):
    for role in ("customer", "analyst", "manager"):
        r = client.get(f"{API}/admin/users", headers=h[role])
        assert r.status_code == 403 and r.json()["error_code"] == "FORBIDDEN"
    assert client.get(f"{API}/admin/analysts", headers=h["manager"]).status_code == 200


def test_passwords_never_stored_or_logged(client):
    client.post(f"{API}/auth/login", json={"email": "customer@finora.dev", "password": "MySecret999"})
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == "customer@finora.dev")).one()
        assert u.password_hash.startswith("$argon2id$")
        text_blob = " ".join(e.event_description for e in db.scalars(select(AuditEvent)).all())
        assert "MySecret999" not in text_blob and "Customer@123" not in text_blob


def test_audit_chain_valid_then_tamper_detected(client, h):
    with SessionLocal() as db:
        result = verify_chain(db)
        assert result["valid"] and result["checked"] >= 6
        # Simulate an attacker editing an old row directly in the database
        db.execute(text("UPDATE audit_events SET event_description = 'nothing happened' WHERE sequence_number = 2"))
        db.commit()
        broken = verify_chain(db)
        assert broken["valid"] is False and broken["first_broken_sequence"] == 2