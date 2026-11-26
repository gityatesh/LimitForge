"""Step 2 unit tests: no database needed."""
from fastapi.testclient import TestClient

from app.core.security import (
    create_access_token, decode_access_token, hash_password, hash_token, new_secret_token, verify_password,
)
from app.main import app


def test_password_hash_is_argon2id_and_salted():
    h1, h2 = hash_password("Secret@123"), hash_password("Secret@123")
    assert h1.startswith("$argon2id$")
    assert h1 != h2                      # different random salt each time
    assert verify_password("Secret@123", h1)
    assert not verify_password("wrong", h1)
    assert not verify_password("Secret@123", "not-a-hash")


def test_jwt_roundtrip_and_tamper_detection():
    token = create_access_token("abc", "ADMIN")
    assert decode_access_token(token)["sub"] == "abc"
    assert decode_access_token(token[:-2] + "xx") is None     # tampered
    assert decode_access_token("garbage") is None


def test_reset_token_only_hash_is_stored():
    raw, hashed = new_secret_token()
    assert raw != hashed and len(hashed) == 64 and hash_token(raw) == hashed


def test_health_and_error_envelope():
    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok"}
    body = c.get("/does-not-exist").json()
    assert set(body) == {"error_code", "message", "details"} and body["error_code"] == "NOT_FOUND"