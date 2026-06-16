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

from services.log_service import write_audit_log

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

    user_id = _uuid.UUID(payload.get("sub")) if payload else None
    if db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first():
        write_audit_log(
            action="GET_CURRENT_USER",
            resource="USER",
            result="error",
            user_id= user_id,
            resource_id=user_id,
            message=f"Revoked token was presented",
            db=db
        )
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
            write_audit_log(
                action="GET_CURRENT_USER",
                resource="USER",
                result="error",
                user_id=user.id,
                resource_id=user.id,
                message=f"Request rejected: iat predates revocation cutoff for user={user.id}",
                db=db
            )
            _deny("Token has been revoked")

    # Stash roles claim so role checks don't require an extra DB hit
    user._jwt_roles = payload.get("roles", [])  # type: ignore[attr-defined]
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but never raises — returns None when no valid
    credentials are present. For endpoints that are public but tailor their
    response to the caller (e.g. showing a seller their own draft products).
    """
    if credentials is None:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


def require_role(*allowed_role_names: str):
    """Returns a dependency that allows the request only if the user has at
    least one of the given roles. Matching is case-insensitive.
    """
    allowed_lower = {r.lower() for r in allowed_role_names}

    def _check(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        user_roles = {r.lower() for r in getattr(current_user, "_jwt_roles", [])}
        if user_roles.isdisjoint(allowed_lower):
            write_audit_log(
                action="REQUIRE_ROLE",
                resource="USER",
                result="error",
                user_id=current_user.id,
                resource_id=current_user.id,
                message=f"RBAC denial: user={current_user.id} roles={sorted(user_roles)} required_one_of={sorted(allowed_lower)}",
                db=db
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
