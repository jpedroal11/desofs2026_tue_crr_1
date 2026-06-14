"""Auth routes. Each route:
  1. Receives a validated request (Pydantic handles structure + password rules)
  2. Calls services/auth_service
  3. Maps service exceptions to HTTP status codes
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.config import get_settings
from core.dependencies import get_db
from middleware.auth import get_current_user, require_admin
from models.models import User
from schemas.schemas import (
    AccessTokenResponse,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from services import auth_service as svc

from services.log_service import write_audit_log

router = APIRouter(prefix="/auth", tags=["Authentication"])

_bearer = HTTPBearer(auto_error=True)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(data: UserCreate, db: Session = Depends(get_db)):
    try:
        user = await svc.register_user(data, db)
    except svc.EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    except svc.UsernameAlreadyTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    except svc.BreachedPassword:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This password has appeared in a known data breach. Please choose a different one.",
        )
    except svc.RoleNotAllowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Registration with the Administrator role is not permitted.",
        )
    return user


@router.post(
    "/user/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def register_admin(data: UserCreate, db: Session = Depends(get_db)):
    # Delegates to the same service path as the public route — same exception
    # handling so behaviour stays consistent. allow_admin=True means
    # RoleNotAllowed won't fire here, but we map it anyway so future changes
    # to the service can't silently leak a 500.
    try:
        user = await svc.register_user(data, db, allow_admin=True)
    except svc.EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    except svc.UsernameAlreadyTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    except svc.BreachedPassword:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This password has appeared in a known data breach. Please choose a different one.",
        )
    except svc.RoleNotAllowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Registration with the Administrator role is not permitted.",
        )
    return user


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        tokens = svc.login_user(data, db)
    except svc.AccountLocked:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account temporarily locked due to repeated failed logins. "
            f"Try again in {svc.LOCKOUT_MINUTES} minutes.",
        )
    except svc.AccountDisabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    except svc.InvalidCredentials:
        # Same generic 401 for wrong-password and unknown-email — no enumeration
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    body: LogoutRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
):
    refresh_token = body.refresh_token if body else None
    svc.logout_user(credentials.credentials, db, refresh_token=refresh_token)
    return MessageResponse(message="Logged out")


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    """Rotates the refresh token — the supplied token is single-use; the
    response always contains a fresh access AND refresh token. Clients must
    replace both."""
    try:
        tokens = svc.refresh_access_token(data.refresh_token, db)
    except svc.InvalidToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


@router.post("/password-reset/request")
def password_reset_request(data: PasswordResetRequest, db: Session = Depends(get_db)):
    """Always returns the same response — never reveals whether the email is
    registered. In production the token is emailed; outside production we
    surface it in the response so developers/tests can use it directly.
    """
    raw_token = svc.request_password_reset(data.email, db)
    response = {"message": "If that email is registered, a reset link has been sent."}
    if raw_token and get_settings().app_env.lower() != "production":
        response["_dev_token"] = raw_token
    return response


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def password_reset_confirm(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    try:
        await svc.confirm_password_reset(data.token, data.new_password, db)
    except svc.InvalidToken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")
    except svc.BreachedPassword:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This password has appeared in a known data breach. Please choose a different one.",
        )
    return MessageResponse(message="Password updated successfully")


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
