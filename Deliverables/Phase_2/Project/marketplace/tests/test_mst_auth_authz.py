"""Manual Security Tests — Authentication & Authorisation abuse cases.

Owner: Pedro Leal (Auth & Authz scope).

Each test maps 1:1 to an MST case from the Phase 1 report (§8.6) and asserts
the security requirement is enforced. Test IDs and requirement tags are kept in
the docstrings so the traceability matrix can cite this file directly.

Covered here:
  Authentication:  MST-01, MST-02, MST-04, MST-NEW-01..04
  Authorisation:   MST-05..09, MST-NEW-05, MST-NEW-06

Not covered (other owners / modules):
  MST-03  JWT signature tampering          -> middleware tests (Pedro D. Nunes)
  MST-08  /audit-log function-level check   -> audit module (Pedro D. Nunes)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from models.models import Product, ProductStatus, Role, User
from core.security import hash_password


GOOD_PASSWORD = "Str0ng!Password123"
WRONG_PASSWORD = "Wr0ng!Password123"


# HIBP is mocked for the whole module — registration must not hit the real API.
@pytest.fixture(autouse=True)
def mock_pwned():
    with patch("services.auth_service.is_password_breached", return_value=False) as m:
        yield m


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client, email, username, password=GOOD_PASSWORD, role="Buyer"):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "full_name": "MST User",
            "password": password,
            "roles": [role],
        },
    )


def _login(client, email, password=GOOD_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# Authentication Abuse Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_mst_01_brute_force_locks_account(client, db_session):
    """MST-01 / SR-AUTH-07, SR-AUTH-09 — credential stuffing / brute force.

    5 wrong-password attempts lock the account; the 6th attempt (even with the
    correct password) is rejected with HTTP 423 Locked.
    """
    _register(client, "brute@x.com", "brute")
    for _ in range(5):
        _login(client, "brute@x.com", WRONG_PASSWORD)

    r = _login(client, "brute@x.com", GOOD_PASSWORD)
    assert r.status_code == 423

    user = db_session.query(User).filter(User.email == "brute@x.com").first()
    assert user.failed_login_attempts == 5
    assert user.locked_until is not None


@pytest.mark.skip(
    reason="MST-02: IP-based rate limiting depends on the rate-limit middleware "
    "(owner: Pedro D. Nunes) which is not yet implemented."
)
def test_mst_02_ip_rate_limiting(client):
    """MST-02 / SR-AUTH-09 — 5 login requests from the same IP within 1 minute
    should return HTTP 429."""
    for _ in range(6):
        r = _login(client, "nobody@x.com", WRONG_PASSWORD)
    assert r.status_code == 429


def test_mst_04_refresh_after_deactivation_denied(client, db_session):
    """MST-04 / SR-AUTH-08 — a refresh token must stop working once the account
    is deactivated."""
    _register(client, "deact@x.com", "deact")
    tokens = _login(client, "deact@x.com").json()

    user = db_session.query(User).filter(User.email == "deact@x.com").first()
    user.is_active = False
    db_session.commit()

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_mst_new_01_breached_password_rejected_at_registration(client, mock_pwned):
    """MST-NEW-01 / SR-AUTH-04 — a known-breached password is rejected at
    registration (HIBP k-anonymity check)."""
    mock_pwned.return_value = True
    r = _register(client, "breach@x.com", "breach")
    assert r.status_code == 400
    assert "breach" in r.json()["detail"].lower()


def test_mst_new_02_lockout_expires_after_30_minutes(client, db_session):
    """MST-NEW-02 / SR-AUTH-07, SR-AUTH-09 — the lock is set ~30 minutes out and
    a login succeeds once that window has passed."""
    _register(client, "expire@x.com", "expire")
    for _ in range(5):
        _login(client, "expire@x.com", WRONG_PASSWORD)

    user = db_session.query(User).filter(User.email == "expire@x.com").first()
    remaining = _aware(user.locked_until) - datetime.now(timezone.utc)
    assert timedelta(minutes=25) < remaining <= timedelta(minutes=30)

    # Simulate the lock window elapsing
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    r = _login(client, "expire@x.com", GOOD_PASSWORD)
    assert r.status_code == 200


def test_mst_new_03_refresh_invalidated_after_password_change(client):
    """MST-NEW-03 / SR-AUTH-08 — changing the password (via reset) invalidates
    previously-issued refresh tokens."""
    _register(client, "pwchg@x.com", "pwchg")
    tokens = _login(client, "pwchg@x.com").json()

    reset_token = client.post(
        "/auth/password-reset/request", json={"email": "pwchg@x.com"}
    ).json()["_dev_token"]
    client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "An0therStr0ng!Pass"},
    )

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_mst_new_04_secret_key_has_no_default(monkeypatch):
    """MST-NEW-04 / SR-AUTH-06 — the app refuses to start without an explicit
    SECRET_KEY (no hardcoded fallback that could leak into a deployment)."""
    from pydantic import ValidationError
    from core.config import Settings

    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        # _env_file=None so a local .env can't supply the value
        Settings(_env_file=None, database_url="sqlite:///:memory:")


# ══════════════════════════════════════════════════════════════════════════════
# Authorisation Abuse Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_mst_05_idor_on_orders(buyer_a_client, buyer_b_order_id):
    """MST-05 / SR-AUTHZ-02, SR-AUTHZ-04 — Buyer A cannot read Buyer B's order."""
    r = buyer_a_client.get(f"/orders/{buyer_b_order_id}")
    assert r.status_code == 403


def test_mst_06_idor_on_products_cross_seller(seller_a_client, seller_b_product_id):
    """MST-06 / SR-AUTHZ-05 — Seller A cannot modify Seller B's product."""
    r = seller_a_client.patch(
        f"/products/{seller_b_product_id}", json={"name": "hacked"}
    )
    assert r.status_code == 403


def test_mst_07_role_field_cannot_be_self_assigned(buyer_client, seed_buyer):
    """MST-07 / SR-AUTHZ-03 — a buyer cannot escalate to admin via a stray
    `role` field on the profile-update payload (field is not modelled, so it is
    silently ignored)."""
    r = buyer_client.patch(
        f"/users/{seed_buyer['id']}", json={"role": "ADMIN", "roles": ["Administrator"]}
    )
    assert r.status_code == 200
    assert all(role["name"] != "Administrator" for role in r.json()["roles"])


def test_mst_08_function_level_access_control(buyer_client):
    """MST-08 / SR-AUTHZ-01, SR-AUTHZ-02 — a buyer cannot list all users.

    NOTE: the /audit-log half of MST-08 belongs to the audit module
    (owner: Pedro D. Nunes) and is asserted in that module's tests.
    """
    assert buyer_client.get("/users/").status_code == 403


def test_mst_09_buyer_cannot_access_draft_product(client, db_session, seed_seller, seed_buyer):
    """MST-09 / SR-AUTHZ-06 — a draft product is not visible to a buyer."""
    seller = db_session.query(User).filter(User.email == seed_seller["email"]).first()
    draft = Product(
        name="Secret Draft",
        description="Not published yet.",
        price=10.0,
        stock=5,
        seller_id=seller.id,
        status=ProductStatus.draft,
    )
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)

    buyer_token = _login(client, seed_buyer["email"], seed_buyer["password"]).json()[
        "access_token"
    ]
    r = client.get(f"/products/{draft.id}", headers=_bearer(buyer_token))
    assert r.status_code == 404  # existence not disclosed

    # ...and the owning seller CAN still see their own draft
    seller_token = _login(client, seed_seller["email"], seed_seller["password"]).json()[
        "access_token"
    ]
    r_owner = client.get(f"/products/{draft.id}", headers=_bearer(seller_token))
    assert r_owner.status_code == 200


def test_mst_new_05_invoice_scoped_to_owning_buyer(buyer_a_client, buyer_b_order_id):
    """MST-NEW-05 / SR-AUTHZ-04, SR-DATA-08 — Buyer A cannot download the invoice
    for Buyer B's order."""
    r = buyer_a_client.get(f"/orders/{buyer_b_order_id}/invoice")
    assert r.status_code == 403


def test_mst_new_06_image_uuid_guessing_returns_not_found(client):
    """MST-NEW-06 / SR-AUTHZ-02, SR-DATA-03 — a guessed image filename returns
    404. Images are served by unguessable UUID filenames by design; a random
    guess discloses nothing."""
    import uuid

    r = client.get(f"/images/{uuid.uuid4()}.png")
    assert r.status_code == 404
