import pytest

class TestLogin:
    """SR-AUTH-01, SR-AUTH-07, SR-AUTH-09"""

    def test_login_with_valid_credentials_returns_200(self, client, seed_buyer):
        response = client.post("/api/v1/auth/login", json={
            "email": seed_buyer["email"],
            "password": seed_buyer["password"]
        })
        assert response.status_code == 200
        assert "access_token" in response.json()
        assert "refresh_token" in response.json()

    def test_login_with_wrong_password_returns_401(self, client, seed_buyer):
        response = client.post("/api/v1/auth/login", json={
            "email": seed_buyer["email"],
            "password": "wrongpassword"
        })
        assert response.status_code == 401

    def test_login_error_message_does_not_reveal_user_existence(
        self, client, seed_buyer
    ):
        """NFR-09 — same message whether user exists or not"""
        response_wrong_pass = client.post("/api/v1/auth/login", json={
            "email": seed_buyer["email"],
            "password": "wrong"
        })
        response_no_user = client.post("/api/v1/auth/login", json={
            "email": "doesnotexist@test.com",
            "password": "wrong"
        })
        assert response_wrong_pass.json()["detail"] == \
               response_no_user.json()["detail"]

    def test_account_locks_after_5_failed_attempts(self, client, seed_buyer):
        """SR-AUTH-07, MST-01"""
        for _ in range(5):
            client.post("/api/v1/auth/login", json={
                "email": seed_buyer["email"],
                "password": "wrong"
            })
        response = client.post("/api/v1/auth/login", json={
            "email": seed_buyer["email"],
            "password": seed_buyer["password"]  # correct password
        })
        assert response.status_code in [403, 429]

    def test_access_token_expiry_is_short(self, client, seed_buyer):
        """SR-AUTH-05 — max 15 minutes"""
        import jwt as pyjwt
        response = client.post("/api/v1/auth/login", json={
            "email": seed_buyer["email"],
            "password": seed_buyer["password"]
        })
        token = response.json()["access_token"]
        # Decode without verification just to read claims
        payload = pyjwt.decode(
            token, options={"verify_signature": False}
        )
        issued_at = payload["iat"]
        expires_at = payload["exp"]
        ttl_minutes = (expires_at - issued_at) / 60
        assert ttl_minutes <= 15
