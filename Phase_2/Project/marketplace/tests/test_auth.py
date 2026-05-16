"""End-to-end tests for the auth routes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from models.models import PasswordResetToken, User


GOOD_PASSWORD = "Str0ng!Password123"
ANOTHER_GOOD = "An0therStr0ng!Pass"


# Patch HIBP for the whole module — we don't want to hit the real API in tests
@pytest.fixture(autouse=True)
def mock_pwned():
    with patch("services.auth_service.is_password_breached", return_value=False) as m:
        yield m


def _payload(email="bob@x.com", username="bob", password=GOOD_PASSWORD, role="Buyer"):
    return {
        "email": email,
        "username": username,
        "full_name": "Test User",
        "password": password,
        "roles": [role],
    }


def _register(client, **overrides):
    return client.post("/auth/register", json=_payload(**overrides))


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_success(client, db_session):
    r = client.post("/auth/register", json=_payload(email="alice@example.com", username="alice"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["username"] == "alice"
    assert "id" in body
    assert "password" not in body and "hashed_password" not in body
    assert any(r["name"] == "Buyer" for r in body["roles"])

    user = db_session.query(User).filter(User.email == "alice@example.com").first()
    assert user is not None
    assert user.hashed_password != GOOD_PASSWORD  # actually hashed


def test_register_weak_password_rejected(client):
    r = client.post("/auth/register", json=_payload(password="short"))
    assert r.status_code == 422  # pydantic validation


def test_register_duplicate_email(client):
    assert _register(client).status_code == 201
    # Same email, different username — still a conflict
    r = client.post("/auth/register", json=_payload(username="bob2"))
    assert r.status_code == 409


def test_register_duplicate_username(client):
    assert _register(client).status_code == 201
    r = client.post("/auth/register", json=_payload(email="other@x.com"))
    assert r.status_code == 409


def test_register_breached_password_blocked(client, mock_pwned):
    mock_pwned.return_value = True
    r = _register(client)
    assert r.status_code == 400
    assert "breach" in r.json()["detail"].lower()


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_success_returns_tokens(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password_returns_401(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "bob@x.com", "password": "WrongPass!1234"})
    assert r.status_code == 401


def test_login_unknown_email_returns_same_401(client):
    """No user enumeration — same response as wrong password."""
    r = client.post("/auth/login", json={"email": "nobody@x.com", "password": GOOD_PASSWORD})
    assert r.status_code == 401


def test_login_locks_after_5_failures(client, db_session):
    _register(client)
    for _ in range(5):
        client.post("/auth/login", json={"email": "bob@x.com", "password": "wrong!Pass1234"})

    # 6th attempt — even with the correct password — gets 423 Locked
    r = client.post("/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD})
    assert r.status_code == 423

    user = db_session.query(User).filter(User.email == "bob@x.com").first()
    assert user.locked_until is not None
    assert user.failed_login_attempts == 5


def test_login_resets_counter_on_success(client, db_session):
    _register(client)
    for _ in range(3):
        client.post("/auth/login", json={"email": "bob@x.com", "password": "wrong!Pass1234"})

    client.post("/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD})

    user = db_session.query(User).filter(User.email == "bob@x.com").first()
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


# ── Logout (token blacklisting) ───────────────────────────────────────────────

def test_logout_blacklists_token(client):
    _register(client)
    tokens = client.post(
        "/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD}
    ).json()
    access = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


# ── Refresh ───────────────────────────────────────────────────────────────────

def test_refresh_returns_new_access_token(client):
    _register(client)
    tokens = client.post(
        "/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD}
    ).json()

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_access = r.json()["access_token"]
    assert new_access and new_access != tokens["access_token"]

    assert client.get(
        "/auth/me", headers={"Authorization": f"Bearer {new_access}"}
    ).status_code == 200


def test_refresh_with_access_token_rejected(client):
    """An access token must NOT be usable in /refresh."""
    _register(client)
    tokens = client.post(
        "/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD}
    ).json()
    r = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


def test_refresh_with_garbage_returns_401(client):
    r = client.post("/auth/refresh", json={"refresh_token": "not.a.token"})
    assert r.status_code == 401


# ── Password reset ────────────────────────────────────────────────────────────

def test_password_reset_request_existing_email(client):
    _register(client)
    r = client.post("/auth/password-reset/request", json={"email": "bob@x.com"})
    assert r.status_code == 200
    body = r.json()
    assert "_dev_token" in body


def test_password_reset_request_unknown_email_same_response(client):
    """No enumeration — unknown email returns same status & message."""
    r1 = client.post("/auth/password-reset/request", json={"email": "nobody@x.com"})
    _register(client)
    r2 = client.post("/auth/password-reset/request", json={"email": "bob@x.com"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["message"] == r2.json()["message"]


def test_password_reset_confirm_changes_password(client):
    _register(client)
    token = client.post(
        "/auth/password-reset/request", json={"email": "bob@x.com"}
    ).json()["_dev_token"]

    r = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": ANOTHER_GOOD},
    )
    assert r.status_code == 200

    assert client.post(
        "/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "bob@x.com", "password": ANOTHER_GOOD}
    ).status_code == 200


def test_password_reset_token_single_use(client):
    _register(client)
    token = client.post(
        "/auth/password-reset/request", json={"email": "bob@x.com"}
    ).json()["_dev_token"]

    assert client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": ANOTHER_GOOD},
    ).status_code == 200
    assert client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": "Y3tAn0ther!Pass"},
    ).status_code == 400


def test_password_reset_invalid_token(client):
    r = client.post(
        "/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": ANOTHER_GOOD},
    )
    assert r.status_code == 400


def test_password_reset_expired_token(client, db_session):
    _register(client)
    token = client.post(
        "/auth/password-reset/request", json={"email": "bob@x.com"}
    ).json()["_dev_token"]

    record = db_session.query(PasswordResetToken).first()
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    r = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": ANOTHER_GOOD},
    )
    assert r.status_code == 400


def test_password_reset_clears_lockout(client, db_session):
    _register(client)
    for _ in range(5):
        client.post("/auth/login", json={"email": "bob@x.com", "password": "wrong!Pass1234"})

    user = db_session.query(User).filter(User.email == "bob@x.com").first()
    assert user.locked_until is not None

    token = client.post(
        "/auth/password-reset/request", json={"email": "bob@x.com"}
    ).json()["_dev_token"]
    client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": ANOTHER_GOOD},
    )

    db_session.refresh(user)
    assert user.locked_until is None
    assert user.failed_login_attempts == 0
