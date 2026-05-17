import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from middleware.auth import get_current_user, require_role
from core.security import create_access_token, verify_password, hash_password
from models.models import User, Role
from datetime import timedelta
from unittest.mock import patch
import uuid

def test_verify_password():
    password = "MySecurePassword123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False

def test_get_current_user_missing_creds(db_session):
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=None, db=db_session)
    assert exc.value.status_code == 401
    assert "Missing" in exc.value.detail

def test_get_current_user_no_user(db_session):
    token = create_access_token(str(uuid.uuid4()), [])[0]
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds, db=db_session)
    assert exc.value.status_code == 401
    assert "not found" in exc.value.detail

def test_get_current_user_invalid_token(db_session):
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token.string")
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds, db=db_session)
    assert exc.value.status_code == 401
    assert "Invalid or expired token" in exc.value.detail

def test_get_current_user_expired_token(db_session, buyer_user):
    from core.security import _build_token
    token = _build_token(str(buyer_user.id), {"roles": ["Buyer"], "type": "access"}, timedelta(minutes=-1))[0]
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds, db=db_session)
    assert exc.value.status_code == 401
    assert "Invalid or expired token" in exc.value.detail

def test_get_current_user_revoked_token(db_session, buyer_user):
    token = create_access_token(str(buyer_user.id), [])[0]
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    
    # Revoke it
    from services.auth_service import logout_user
    logout_user(token, db_session)
    
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds, db=db_session)
    assert exc.value.status_code == 401
    assert "revoked" in exc.value.detail

def test_require_role():
    # Require role returns a dependency function
    dep = require_role("Administrator")
    
    # User with Admin role
    admin_user = User(email="admin@test.com", username="admin", hashed_password="pw")
    admin_user._jwt_roles = ["Administrator"]
    
    assert dep(admin_user) == admin_user
    
    # User without Admin role
    buyer_user = User(email="buyer@test.com", username="buyer", hashed_password="pw")
    buyer_user._jwt_roles = ["Buyer"]
    
    with pytest.raises(HTTPException) as exc:
        dep(buyer_user)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient permissions"

    # User with multiple roles, one matches
    multi_user = User(email="multi@test.com", username="multi", hashed_password="pw")
    multi_user._jwt_roles = ["Buyer", "Administrator"]
    assert dep(multi_user) == multi_user
