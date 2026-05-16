"""Auth business logic. Routes are thin wrappers around these functions.

Security properties enforced here:
  - bcrypt password hashing
  - HIBP k-anonymity breach check on register & reset
  - No user enumeration (uniform InvalidCredentials for unknown email or wrong
    password) + constant-time verify even when user is missing
  - Account lockout (5 attempts -> 15-minute lock)
  - Reset tokens stored only as SHA-256 hashes, single-use, 30-min TTL
  - JWT jti claim enables blacklist-based revocation
  - Refresh tokens carry type=refresh so they cannot be used as access tokens
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from core.config import get_settings
from core.roles import UserRole
from core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from models.models import (
    PasswordResetToken,
    Role,
    TokenBlacklist,
    User,
)
from schemas.schemas import LoginRequest, UserCreate
from services.pwned import is_password_breached

logger = logging.getLogger(__name__)
settings = get_settings()

# Policy constants
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
RESET_TOKEN_EXPIRE_MINUTES = 30

# Real bcrypt hash that nothing matches — used to keep login timing constant
# when the email is not registered (defends against enumeration via timing).
DUMMY_BCRYPT_HASH = "$2b$12$KIXGhKMaGXkOHRLCkCHBtOFf5DqkWGqNlEkUBBMCL5LoV7vd9SiKi"

DEFAULT_ROLE_NAME = UserRole.BUYER.value
ADMINISTRATOR_ROLE_NAME = UserRole.ADMIN.value


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str


class AuthError(Exception):
    """Base for all auth-service errors."""


class EmailAlreadyRegistered(AuthError):
    pass


class UsernameAlreadyTaken(AuthError):
    pass


class BreachedPassword(AuthError):
    pass


class InvalidCredentials(AuthError):
    """Generic — covers both wrong password AND unknown email (no enumeration)."""


class AccountLocked(AuthError):
    pass


class AccountDisabled(AuthError):
    pass


class InvalidToken(AuthError):
    pass

class RoleNotAllowed(AuthError):
    pass

# ── Registration ──────────────────────────────────────────────────────────────

async def register_user(data: UserCreate, db: Session, allow_admin: bool = False) -> User:
    if db.query(User).filter(User.email == data.email).first():
        raise EmailAlreadyRegistered()
    if db.query(User).filter(User.username == data.username).first():
        raise UsernameAlreadyTaken()

    if await is_password_breached(data.password):
        raise BreachedPassword()

    role_names = data.roles or [DEFAULT_ROLE_NAME]
    if not allow_admin and any(name.strip().lower() == ADMINISTRATOR_ROLE_NAME.lower() for name in role_names):
        raise RoleNotAllowed()

    user = User(
        email=data.email,
        username=data.username,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
    )

    user.roles = _resolve_roles(role_names, db)

    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("User registered: id=%s roles=%s", user.id, [r.name for r in user.roles])
    return user


# ── Login ─────────────────────────────────────────────────────────────────────

def login_user(data: LoginRequest, db: Session) -> TokenPair:
    """All failure paths raise InvalidCredentials so the HTTP layer returns
    the same generic 401 — no enumeration. AccountLocked is separate because
    the user genuinely needs to know their account is locked.
    """
    user = db.query(User).filter(User.email == data.email).first()
    now = datetime.now(timezone.utc)

    # Lockout check first — never increment counter on a locked account
    # (an attacker could otherwise keep an account locked forever).
    if user and user.locked_until and _aware(user.locked_until) > now:
        raise AccountLocked()

    # Verify password — always run bcrypt even when user is None so timing
    # does not reveal whether the email is registered.
    pw_hash = user.hashed_password if user else DUMMY_BCRYPT_HASH
    pw_ok = verify_password(data.password, pw_hash)

    if not user or not pw_ok:
        if user:
            _record_failed_attempt(user, db)
        raise InvalidCredentials()

    if not user.is_active:
        raise AccountDisabled()

    # Success — clear lockout state
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    roles = [r.name for r in user.roles]
    access, _, _ = create_access_token(str(user.id), roles)
    refresh, _, _ = create_refresh_token(str(user.id))

    logger.info("User logged in: id=%s", user.id)
    return TokenPair(access_token=access, refresh_token=refresh)


# ── Logout (blacklist the access token) ───────────────────────────────────────

def logout_user(access_token: str, db: Session) -> None:
    """Idempotent — calling it on an already-invalid token is a no-op."""
    try:
        payload = decode_access_token(access_token)
    except InvalidTokenError:
        return

    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    db.merge(TokenBlacklist(jti=payload["jti"], expires_at=expires_at))
    db.commit()
    logger.info("Token blacklisted: jti=%s", payload["jti"])


# ── Refresh ───────────────────────────────────────────────────────────────────

def refresh_access_token(refresh_token: str, db: Session) -> str:
    try:
        payload = decode_refresh_token(refresh_token)
    except InvalidTokenError:
        raise InvalidToken()

    if db.query(TokenBlacklist).filter(TokenBlacklist.jti == payload["jti"]).first():
        raise InvalidToken()

    user = db.query(User).filter(User.id == uuid.UUID(payload["sub"])).first()
    if not user or not user.is_active:
        raise InvalidToken()

    roles = [r.name for r in user.roles]
    new_access, _, _ = create_access_token(str(user.id), roles)
    return new_access


# ── Password reset — request ──────────────────────────────────────────────────

def request_password_reset(email: str, db: Session) -> str | None:
    """Returns the raw token if the email exists, else None.

    The caller MUST return the same HTTP response in both cases — that is how
    we prevent enumeration. In production the token is emailed; here we let
    the dev surface it in the JSON response.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None

    raw_token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        token_hash=_sha256(raw_token),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
    ))
    db.commit()
    logger.info("Password reset requested: user_id=%s", user.id)
    return raw_token


# ── Password reset — confirm ──────────────────────────────────────────────────

async def confirm_password_reset(token: str, new_password: str, db: Session) -> None:
    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == _sha256(token))
        .first()
    )

    now = datetime.now(timezone.utc)
    if (
        record is None
        or record.used_at is not None
        or _aware(record.expires_at) < now
    ):
        raise InvalidToken()

    if await is_password_breached(new_password):
        raise BreachedPassword()

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise InvalidToken()

    user.hashed_password = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    record.used_at = now
    db.commit()

    logger.info("Password reset completed: user_id=%s", user.id)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _record_failed_attempt(user: User, db: Session) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        logger.warning(
            "Account locked: user_id=%s attempts=%d",
            user.id, user.failed_login_attempts,
        )
    db.commit()


def _resolve_roles(role_names: list[str], db: Session) -> list[Role]:
    """Resolve role names (case-insensitive) to Role rows, creating any that
    do not yet exist. Names are normalised to Title-Case to match the seed
    rows in database/script.sql.
    """
    resolved: list[Role] = []
    for name in role_names:
        norm = name.strip().title()
        role = db.query(Role).filter(Role.name == norm).first()
        if not role:
            role = Role(name=norm)
            db.add(role)
            db.flush()
        resolved.append(role)
    return resolved


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _aware(dt: datetime) -> datetime:
    """SQLite drops tz info on read — re-attach UTC so comparisons work."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
