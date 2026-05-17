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

def test_list_users(client, buyer_user):
    res = client.get("/users/")
    assert res.status_code == 200
    assert len(res.json()) >= 1 # Because fixtures create users

def test_get_user(client, buyer_user):
    user_id = buyer_user.id
    res = client.get(f"/users/{user_id}")
    assert res.status_code == 200
    assert res.json()["id"] == str(user_id)

    # Not found
    res_404 = client.get(f"/users/{uuid.uuid4()}")
    assert res_404.status_code == 404

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

    # Verify soft delete
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
