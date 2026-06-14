import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from core.dependencies import get_db
from middleware.auth import get_current_user, require_admin
from models.models import User
from schemas.schemas import UserResponse, UserUpdate

from services.log_service import write_audit_log

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/",
    response_model=List[UserResponse],
    dependencies=[Depends(require_admin)],
)
def list_users(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    """List all active users. Admin only — the response includes PII (email)
    so it must not be exposed to unauthenticated callers or enumerated by
    non-admins.
    """
    return db.query(User).filter(User.is_active == True).offset(skip).limit(limit).all()


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a user by ID. Authenticated callers only — the response includes
    PII (email) so it cannot be public.
    """
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a user. Users can only update themselves."""
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to update another user")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for field, value in user_in.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a user (sets is_active=False)."""
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to delete another user")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
