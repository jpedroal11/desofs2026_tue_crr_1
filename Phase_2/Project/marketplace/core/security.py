"""JWT issuance/decoding + bcrypt password helpers.

Uses PyJWT (python-jose is abandoned and has unfixable transitive CVEs).
Uses raw bcrypt (matches the team's existing choice in dependencies.py).
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from core.config import get_settings

settings = get_settings()


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. dummy string used for constant-time login fallback)
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _build_token(
    subject: str,
    extra_claims: dict[str, Any],
    expires_delta: timedelta,
) -> tuple[str, str, datetime]:
    """Returns (encoded_token, jti, expires_at)."""
    now = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    jti = str(uuid4())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expires_at,
        "jti": jti,
        **extra_claims,
    }
    encoded = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return encoded, jti, expires_at


def create_access_token(user_id: str, roles: list[str]) -> tuple[str, str, datetime]:
    return _build_token(
        subject=user_id,
        extra_claims={"roles": roles, "type": "access"},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    return _build_token(
        subject=user_id,
        extra_claims={"type": "refresh"},
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

    if payload.get("type") != "access":
        raise InvalidTokenError("Invalid token type")
    if not payload.get("sub") or not payload.get("jti"):
        raise InvalidTokenError("Missing required claims")
    if not isinstance(payload.get("roles"), list):
        raise InvalidTokenError("Missing roles claim")

    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

    if payload.get("type") != "refresh":
        raise InvalidTokenError("Invalid token type")
    if not payload.get("sub") or not payload.get("jti"):
        raise InvalidTokenError("Missing required claims")

    return payload
