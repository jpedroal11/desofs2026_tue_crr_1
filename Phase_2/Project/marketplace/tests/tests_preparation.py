#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE_DIR = REPO_ROOT / "Phase_2" / "Project" / "marketplace"
TESTS_DIR = REPO_ROOT / "Tests"
SEED_DATA_FILE = TESTS_DIR / "test_seed_data.json"
CONFTEXT_FILE = TESTS_DIR / "conftest.py"
DB_FILE = REPO_ROOT / "test_db.sqlite3"
UPLOAD_DIR = REPO_ROOT / "test_uploads"
REQUIREMENTS_FILE = MARKETPLACE_DIR / "requirements.txt"

DEFAULT_ENV = {
    "SECRET_KEY": "test-secret-key-do-not-use-in-prod-1234567890abcdef",
    "DATABASE_URL": f"sqlite:///{DB_FILE}",
    "APP_ENV": "test",
    "UPLOAD_DIR": str(UPLOAD_DIR),
}


def ensure_requirements():
    if REQUIREMENTS_FILE.exists():
        print(f"Installing requirements from {REQUIREMENTS_FILE}...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)]
        )
    else:
        print(f"WARNING: requirements file not found at {REQUIREMENTS_FILE}")


def bootstrap_env():
    for key, value in DEFAULT_ENV.items():
        os.environ.setdefault(key, value)

    if not MARKETPLACE_DIR.exists():
        raise FileNotFoundError(f"Could not find marketplace directory at {MARKETPLACE_DIR}")

    sys.path.insert(0, str(MARKETPLACE_DIR))
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def import_marketplace_modules():
    from core.dependencies import SessionLocal, engine
    from core.security import hash_password
    from models.models import (
        Base,
        Order,
        OrderItem,
        OrderStatus,
        Product,
        ProductStatus,
        Role,
        User,
    )

    return {
        "SessionLocal": SessionLocal,
        "engine": engine,
        "hash_password": hash_password,
        "Base": Base,
        "Role": Role,
        "User": User,
        "Product": Product,
        "ProductStatus": ProductStatus,
        "Order": Order,
        "OrderItem": OrderItem,
        "OrderStatus": OrderStatus,
    }


def create_database(engine, Base):
    if DB_FILE.exists():
        DB_FILE.unlink()
    Base.metadata.create_all(bind=engine)


def seed_data(modules):
    SessionLocal = modules["SessionLocal"]
    hash_password = modules["hash_password"]
    Base = modules["Base"]
    Role = modules["Role"]
    User = modules["User"]
    Product = modules["Product"]
    ProductStatus = modules["ProductStatus"]
    Order = modules["Order"]
    OrderItem = modules["OrderItem"]
    OrderStatus = modules["OrderStatus"]

    def get_or_create_role(session, name: str):
        role = session.query(Role).filter(Role.name == name).first()
        if role is None:
            role = Role(name=name)
            session.add(role)
            session.flush()
        return role

    def make_user(session, email, username, password, roles):
        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
        )
        for role_name in roles:
            user.roles.append(get_or_create_role(session, role_name))
        session.add(user)
        session.flush()
        return user

    session = SessionLocal()
    try:
        # ensure a clean start
        Base.metadata.drop_all(bind=modules["engine"])
        Base.metadata.create_all(bind=modules["engine"])

        buyer_a = make_user(
            session,
            email="buyer@test.com",
            username="buyer_a",
            password="BuyerPass123!",
            roles=["Buyer"],
        )
        buyer_b = make_user(
            session,
            email="buyerb@test.com",
            username="buyer_b",
            password="BuyerPass123!",
            roles=["Buyer"],
        )
        seller_a = make_user(
            session,
            email="seller@test.com",
            username="seller_a",
            password="SellerPass123!",
            roles=["Seller"],
        )
        seller_b = make_user(
            session,
            email="sellerb@test.com",
            username="seller_b",
            password="SellerPass123!",
            roles=["Seller"],
        )
        admin = make_user(
            session,
            email="admin@test.com",
            username="admin_user",
            password="AdminPass123!",
            roles=["Administrator"],
        )

        active_product = Product(
            name="Active Product",
            description="A product that is visible to buyers.",
            price=29.99,
            stock=10,
            status=ProductStatus.active,
            seller_id=seller_a.id,
        )
        session.add(active_product)
        session.flush()

        seller_b_product = Product(
            name="Seller B Product",
            description="Seller B's product.",
            price=49.99,
            stock=5,
            status=ProductStatus.active,
            seller_id=seller_b.id,
        )
        session.add(seller_b_product)
        session.flush()

        delivered_order = Order(
            buyer_id=buyer_a.id,
            seller_id=seller_a.id,
            status=OrderStatus.delivered,
            total_amount=float(active_product.price),
            shipping_address="123 Test St, Porto, PT",
        )
        session.add(delivered_order)
        session.flush()

        delivered_item = OrderItem(
            order_id=delivered_order.id,
            product_id=active_product.id,
            quantity=1,
            unit_price=float(active_product.price),
        )
        session.add(delivered_item)

        buyer_b_order = Order(
            buyer_id=buyer_b.id,
            seller_id=seller_b.id,
            status=OrderStatus.pending,
            total_amount=float(seller_b_product.price),
            shipping_address="456 Other St, Lisbon, PT",
        )
        session.add(buyer_b_order)
        session.flush()

        buyer_b_item = OrderItem(
            order_id=buyer_b_order.id,
            product_id=seller_b_product.id,
            quantity=1,
            unit_price=float(seller_b_product.price),
        )
        session.add(buyer_b_item)

        session.commit()

        seed = {
            "buyer_a": {
                "email": buyer_a.email,
                "password": "BuyerPass123!",
                "id": str(buyer_a.id),
            },
            "buyer_b": {
                "email": buyer_b.email,
                "password": "BuyerPass123!",
                "id": str(buyer_b.id),
            },
            "seller_a": {
                "email": seller_a.email,
                "password": "SellerPass123!",
                "id": str(seller_a.id),
            },
            "seller_b": {
                "email": seller_b.email,
                "password": "SellerPass123!",
                "id": str(seller_b.id),
            },
            "active_product": {
                "id": active_product.id,
                "price": float(active_product.price),
                "stock": active_product.stock,
            },
            "seller_b_product": {
                "id": seller_b_product.id,
                "price": float(seller_b_product.price),
                "stock": seller_b_product.stock,
            },
            "delivered_order": {
                "id": delivered_order.id,
                "product_id": delivered_item.product_id,
                "total_amount": float(delivered_order.total_amount),
            },
            "buyer_b_order": {"id": buyer_b_order.id},
        }

        with open(SEED_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(seed, f, indent=2)

        print(f"Seeded test data into {SEED_DATA_FILE}")
        return seed
    finally:
        session.close()


def generate_tests_conftest(seed_data):
    if CONFTEXT_FILE.exists():
        print(f"{CONFTEXT_FILE} already exists, skipping generation.")
        return

    content = f'''"""
Auto-generated test fixtures for the root Tests/ suite.
Generated by test_preparation.py.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE_DIR = REPO_ROOT / "Phase_2" / "Project" / "marketplace"
sys.path.insert(0, str(MARKETPLACE_DIR))

DB_FILE = REPO_ROOT / "test_db.sqlite3"
UPLOAD_DIR = REPO_ROOT / "test_uploads"

os.environ.setdefault("SECRET_KEY", "{DEFAULT_ENV['SECRET_KEY']}")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{{DB_FILE}}")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("UPLOAD_DIR", str(UPLOAD_DIR))

from main import app as marketplace_app  # noqa: E402

test_app = FastAPI()
test_app.mount("/api/v1", marketplace_app)

SEED_FILE = Path(__file__).resolve().parent / "test_seed_data.json"
with open(SEED_FILE, "r", encoding="utf-8") as f:
    SEED = json.load(f)


@pytest.fixture
def client():
    return TestClient(test_app)


def _login_client(email: str, password: str):
    client = TestClient(test_app)
    response = client.post(
        "/api/v1/auth/login",
        json={{"email": email, "password": password}},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {{token}}"
    return client


@pytest.fixture
def seed_buyer():
    return SEED["buyer_a"]


@pytest.fixture
def seed_seller():
    return SEED["seller_a"]


@pytest.fixture
def buyer_client():
    return _login_client(
        SEED["buyer_a"]["email"],
        SEED["buyer_a"]["password"],
    )


@pytest.fixture
def seller_client():
    return _login_client(
        SEED["seller_a"]["email"],
        SEED["seller_a"]["password"],
    )


@pytest.fixture
def buyer_a_client(buyer_client):
    return buyer_client


@pytest.fixture
def seller_a_client(seller_client):
    return seller_client


@pytest.fixture
def buyer_b_order_id():
    return SEED["buyer_b_order"]["id"]


@pytest.fixture
def seller_b_product_id():
    return SEED["seller_b_product"]["id"]


@pytest.fixture
def active_product():
    return SEED["active_product"]


@pytest.fixture
def delivered_order():
    return SEED["delivered_order"]
'''
    with open(CONFTEXT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Generated {CONFTEXT_FILE}")


def main():
    print("Preparing test environment...")
    ensure_requirements()
    bootstrap_env()
    modules = import_marketplace_modules()
    create_database(modules["engine"], modules["Base"])
    seed = seed_data(modules)
    generate_tests_conftest(seed)
    print("Test preparation is complete.")
    print("Run the test suite with: pytest Tests/")


if __name__ == "__main__":
    main()