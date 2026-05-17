# tests/conftest.py
import pytest
from httpx import TestClient

# This import will fail until the app exists — that's fine
# from app.main import app  

@pytest.fixture
def client():
    # Replace with: TestClient(app) when app exists
    pass

@pytest.fixture
def seed_buyer():
    return {
        "email": "buyer@test.com",
        "password": "BuyerPass123!",
        "id": "placeholder-uuid"
    }

@pytest.fixture
def seed_seller():
    return {
        "email": "seller@test.com", 
        "password": "SellerPass123!",
        "id": "placeholder-uuid"
    }

@pytest.fixture
def buyer_client(client, seed_buyer):
    # Will authenticate once client exists
    pass

@pytest.fixture
def seller_client(client, seed_seller):
    pass

@pytest.fixture
def active_product():
    return {
        "id": "placeholder-uuid",
        "price": 29.99,
        "stock": 10
    }