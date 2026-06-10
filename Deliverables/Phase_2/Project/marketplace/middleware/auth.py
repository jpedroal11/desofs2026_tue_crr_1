"""JWT validation + RBAC + blacklist check.

Implemented as FastAPI dependencies (not Starlette BaseHTTPMiddleware) so each
route opts in explicitly. No global allow-list of public paths to maintain.

Use one of:

  current_user: User = Depends(get_current_user)
  # or
  router = APIRouter(..., dependencies=[Depends(require_seller)])
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from core.dependencies import get_db
from core.security import decode_access_token
from models.models import TokenBlacklist, User

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        _deny("Missing Authorization header")

    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        logger.warning("JWT validation failed: %s", exc)
        _deny("Invalid or expired token")

    jti = payload["jti"]
    if db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first():
        logger.warning("Revoked token presented")
        _deny("Token has been revoked")

    user = db.query(User).filter(User.id == _uuid.UUID(payload["sub"])).first()
    if user is None or not user.is_active:
        _deny("User not found or inactive")

    # Reject tokens issued before the user's revocation cutoff (e.g. set by a
    # password reset). SQLite drops tz info on read — re-attach UTC.
    if user.tokens_valid_from is not None:
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        cutoff = user.tokens_valid_from
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        if iat < cutoff:
            logger.warning("Request rejected: iat predates revocation cutoff for user=%s", user.id)
            _deny("Token has been revoked")

    # Stash roles claim so role checks don't require an extra DB hit
    user._jwt_roles = payload.get("roles", [])  # type: ignore[attr-defined]
    return user


def require_role(*allowed_role_names: str):
    """Returns a dependency that allows the request only if the user has at
    least one of the given roles. Matching is case-insensitive.
    """
    allowed_lower = {r.lower() for r in allowed_role_names}

    def _check(current_user: User = Depends(get_current_user)) -> User:
        user_roles = {r.lower() for r in getattr(current_user, "_jwt_roles", [])}
        if user_roles.isdisjoint(allowed_lower):
            logger.warning(
                "RBAC denial: user=%s roles=%s required_one_of=%s",
                current_user.id, sorted(user_roles), sorted(allowed_lower),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _check


# Convenience callables — use as: dependencies=[Depends(require_admin)]
require_authenticated   = get_current_user
require_admin           = require_role("Administrator")
require_seller          = require_role("Seller")
require_buyer           = require_role("Buyer")
require_admin_or_seller = require_role("Administrator", "Seller")


def _deny(detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
