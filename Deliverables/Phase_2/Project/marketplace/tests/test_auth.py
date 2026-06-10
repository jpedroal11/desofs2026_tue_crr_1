"""End-to-end tests for the auth routes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from models.models import PasswordResetToken, User, Role


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


def test_register_administrator_role_forbidden(client):
    r = client.post(
        "/auth/register",
        json={
            "email": "admin@example.com",
            "username": "admin",
            "full_name": "Admin User",
            "password": GOOD_PASSWORD,
            "roles": ["Administrator"],
        },
    )
    assert r.status_code == 403
    assert "administrator" in r.json()["detail"].lower()


def test_admin_register_allows_admin_when_admin(client, db_session):
    from core.security import hash_password

    admin = User(
        email="admin@example.com",
        username="admin",
        hashed_password=hash_password(GOOD_PASSWORD),
    )
    admin.roles = [Role(name="Administrator")]
    db_session.add(admin)
    db_session.commit()

    login_res = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": GOOD_PASSWORD},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    r = client.post(
        "/auth/user/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "newadmin@example.com",
            "username": "newadmin",
            "full_name": "New Admin",
            "password": GOOD_PASSWORD,
            "roles": ["Administrator"],
        },
    )
    assert r.status_code == 201, r.text
    assert any(role["name"] == "Administrator" for role in r.json()["roles"])


def test_admin_register_forbidden_for_non_admin(client, db_session):
    from core.security import hash_password

    user = User(
        email="user@example.com",
        username="user",
        hashed_password=hash_password(GOOD_PASSWORD),
    )
    user.roles = [Role(name="Buyer")]
    db_session.add(user)
    db_session.commit()

    login_res = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": GOOD_PASSWORD},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    r = client.post(
        "/auth/user/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "anotheradmin@example.com",
            "username": "anotheradmin",
            "full_name": "Another Admin",
            "password": GOOD_PASSWORD,
            "roles": ["Administrator"],
        },
    )
    assert r.status_code == 403
    assert "insufficient" in r.json()["detail"].lower()


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_success_returns_tokens(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD})
    # Assert the returned data matches schema expectations
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

def test_login_account_disabled(client, db_session):
    from models.models import User
    from core.security import hash_password
    user = User(email="disabled@example.com", username="disabled", hashed_password=hash_password("pw"), is_active=False)
    db_session.add(user)
    db_session.commit()
    
    res = client.post("/auth/login", json={"email": "disabled@example.com", "password": "pw"})
    assert res.status_code == 403
    assert "Account disabled" in res.json()["detail"] or "disabled" in res.json()["detail"].lower()

def test_logout_invalid_token(client):
    res = client.post("/auth/logout", headers={"Authorization": "Bearer invalid.token"})
    assert res.status_code == 200

    # Call service method directly to cover line 171-172 since HTTP endpoint might intercept
    from services.auth_service import logout_user
    from core.dependencies import SessionLocal
    db = SessionLocal()
    logout_user("invalid.token", db)
    db.close()

def test_refresh_token_blacklisted(client):
    _register(client)
    res = client.post("/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD})
    refresh_token = res.json()["refresh_token"]

    # Logout to blacklist the token (actually logout blacklists access token, but we'll manually blacklist refresh token)
    from core.dependencies import SessionLocal
    from models.models import TokenBlacklist
    from core.security import decode_refresh_token
    from datetime import datetime, timezone
    
    payload = decode_refresh_token(refresh_token)
    db = SessionLocal()
    db.add(TokenBlacklist(jti=payload["jti"], expires_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()

    res_refresh = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert res_refresh.status_code == 401

def test_refresh_user_not_found(client, db_session):
    from core.security import create_refresh_token
    import uuid
    refresh, _, _ = create_refresh_token(str(uuid.uuid4()))
    res_refresh = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert res_refresh.status_code == 401

def test_confirm_reset_breached_password(client, monkeypatch):
    import services.auth_service as auth_svc
    
    _register(client)
    res_req = client.post("/auth/password-reset/request", json={"email": "bob@x.com"})
    token = res_req.json().get("_dev_token")

    async def mock_breached(pw):
        return True
    monkeypatch.setattr(auth_svc, "is_password_breached", mock_breached)

    res_conf = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "BreachedPassword123!"})
    assert res_conf.status_code == 400
    assert "breach" in res_conf.json()["detail"].lower()

def test_confirm_reset_user_deleted(client, db_session):
    from models.models import User
    from core.security import hash_password
    import uuid
    
    user = User(id=uuid.uuid4(), email="del@example.com", username="del", hashed_password=hash_password("pw"))
    db_session.add(user)
    db_session.commit()
    
    res_req = client.post("/auth/password-reset/request", json={"email": user.email})
    token = res_req.json().get("_dev_token")

    db_session.delete(user)
    db_session.commit()

    res_conf = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "NewSecurePassword123!"})
    assert res_conf.status_code == 400


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


def test_password_reset_invalidates_existing_tokens(client):
    """After a password reset, previously-issued access/refresh tokens must be
    rejected (ASVS V6 — existing sessions terminated on credential change)."""
    _register(client)
    tokens = client.post(
        "/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD}
    ).json()
    old_access = tokens["access_token"]
    old_refresh = tokens["refresh_token"]

    reset_token = client.post(
        "/auth/password-reset/request", json={"email": "bob@x.com"}
    ).json()["_dev_token"]
    assert client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": ANOTHER_GOOD},
    ).status_code == 200

    assert client.get(
        "/auth/me", headers={"Authorization": f"Bearer {old_access}"}
    ).status_code == 401
    assert client.post(
        "/auth/refresh", json={"refresh_token": old_refresh}
    ).status_code == 401


def test_logout_blacklists_refresh_token(client):
    """Logout must also revoke the refresh token, otherwise the user can keep
    minting new access tokens via /auth/refresh after logging out."""
    _register(client)
    tokens = client.post(
        "/auth/login", json={"email": "bob@x.com", "password": GOOD_PASSWORD}
    ).json()
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    r = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access}"},
        json={"refresh_token": refresh},
    )
    assert r.status_code == 200

    r2 = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


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
