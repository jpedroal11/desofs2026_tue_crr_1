import pytest
from main import app
from middleware.auth import get_current_user
from models.models import User
import uuid

def authenticate_as(client, user):
    app.dependency_overrides[get_current_user] = lambda: user

def clear_auth(client):
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


def _make_admin(db_session):
    from models.models import Role
    admin = User(
        email="admin-users-tests@example.com",
        username="admin-users-tests",
        hashed_password="hashed_password",
    )
    role = db_session.query(Role).filter(Role.name == "Administrator").first()
    if role is None:
        role = Role(name="Administrator")
        db_session.add(role)
        db_session.flush()
    admin.roles = [role]
    admin._jwt_roles = ["Administrator"]
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    admin._jwt_roles = ["Administrator"]
    return admin


def test_list_users_requires_auth(client):
    """Anonymous listing must be denied — response contains PII (email)."""
    res = client.get("/users/")
    assert res.status_code == 401

def test_list_users_non_admin_forbidden(client, buyer_user):
    authenticate_as(client, buyer_user)
    res = client.get("/users/")
    assert res.status_code == 403
    clear_auth(client)

def test_list_users_admin_ok(client, buyer_user, db_session):
    admin = _make_admin(db_session)
    authenticate_as(client, admin)
    res = client.get("/users/")
    assert res.status_code == 200
    assert len(res.json()) >= 1
    clear_auth(client)

def test_get_user_requires_auth(client, buyer_user):
    res = client.get(f"/users/{buyer_user.id}")
    assert res.status_code == 401

def test_get_user(client, buyer_user):
    user_id = buyer_user.id
    authenticate_as(client, buyer_user)
    res = client.get(f"/users/{user_id}")
    assert res.status_code == 200
    assert res.json()["id"] == str(user_id)

    # Not found
    res_404 = client.get(f"/users/{uuid.uuid4()}")
    assert res_404.status_code == 404
    clear_auth(client)

def test_update_user(client, buyer_user, seller_user):
    user_id = buyer_user.id
    authenticate_as(client, buyer_user)
    
    # Update self
    res = client.patch(f"/users/{user_id}", json={"full_name": "new_buyer_name"})
    assert res.status_code == 200
    assert res.json()["full_name"] == "new_buyer_name"

    # Not found update
    res_404 = client.patch(f"/users/{uuid.uuid4()}", json={"full_name": "x"})
    assert res_404.status_code == 403 # First it checks self, which will fail since current_user.id != random_uuid

    clear_auth(client)

    # Update other user
    authenticate_as(client, seller_user)
    res_403 = client.patch(f"/users/{user_id}", json={"full_name": "hacked"})
    assert res_403.status_code == 403
    clear_auth(client)

def test_update_user_404(client, db_session):
    # Setup an orphan user in db but we act as them so we pass the self check
    new_user = User(
        id=uuid.uuid4(),
        email="orphan@example.com",
        username="orphan",
        hashed_password="hashed_password",
    )
    db_session.add(new_user)
    db_session.commit()
    user_id = new_user.id

    authenticate_as(client, new_user)
    db_session.delete(new_user)
    db_session.commit()

    res = client.patch(f"/users/{user_id}", json={"full_name": "x"})
    assert res.status_code == 404
    clear_auth(client)

def test_delete_user(client, buyer_user, seller_user):
    user_id = buyer_user.id
    
    # Try deleting other user
    authenticate_as(client, seller_user)
    res_403 = client.delete(f"/users/{user_id}")
    assert res_403.status_code == 403
    clear_auth(client)

    # Delete self
    authenticate_as(client, buyer_user)
    res = client.delete(f"/users/{user_id}")
    assert res.status_code == 204

    # Verify soft delete — get_user is now authenticated, so keep the override
    res_get = client.get(f"/users/{user_id}")
    assert res_get.status_code == 404 # Active users only

    clear_auth(client)

def test_delete_user_404(client, db_session):
    new_user = User(
        id=uuid.uuid4(),
        email="orphan2@example.com",
        username="orphan2",
        hashed_password="hashed_password",
    )
    db_session.add(new_user)
    db_session.commit()
    user_id = new_user.id

    authenticate_as(client, new_user)
    db_session.delete(new_user)
    db_session.commit()

    res = client.delete(f"/users/{user_id}")
    assert res.status_code == 404
    clear_auth(client)
