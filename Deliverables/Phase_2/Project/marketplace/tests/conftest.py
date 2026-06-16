"""Shared test fixtures.

Every test gets:
  - A fresh in-memory SQLite database (so tests are isolated)
  - A FastAPI TestClient pointed at it

Required env vars (SECRET_KEY, DATABASE_URL) are set here BEFORE any app
imports — get_settings() is @lru_cached.
"""

import os
import sys

# ── Set env BEFORE any app imports ────────────────────────────────────────────

os.environ.setdefault(
    "SECRET_KEY",
    "test-secret-key-do-not-use-in-prod-min-32-bytes",
)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_ENV", "test")

# Ensure the marketplace directory is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from fastapi.testclient import TestClient

from main import app
from core.dependencies import SessionLocal, engine, get_db
from middleware.auth import get_current_user
import models.models  # noqa: F401 — registers all tables with Base.metadata
from models.models import Base, Role, User


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop and recreate every table before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    """Direct DB session for tests that bypass the API."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client — overrides ``get_db`` to use the test session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── User fixtures with proper roles ───────────────────────────────────────────

def _ensure_role(db, name: str) -> Role:
    role = db.query(Role).filter(Role.name == name).first()
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.flush()
    return role


@pytest.fixture
def seller_user(db_session):
    user = User(
        email="seller@example.com",
        username="seller",
        hashed_password="hashed_password",
    )
    user.roles = [_ensure_role(db_session, "Seller")]
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def buyer_user(db_session):
    user = User(
        email="buyer@example.com",
        username="buyer",
        hashed_password="hashed_password",
    )
    user.roles = [_ensure_role(db_session, "Buyer")]
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_user(db_session):
    user = User(
        email="admin@example.com",
        username="admin",
        hashed_password="hashed_password",
    )
    user.roles = [_ensure_role(db_session, "Administrator")]
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ── Image upload isolation (existing test_images.py depends on this) ──────────

@pytest.fixture(autouse=True)
def tmp_upload_dir(tmp_path, monkeypatch):
    """Redirect image uploads to a temporary directory for test isolation."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    import core.image_service as svc
    monkeypatch.setattr(svc, "UPLOAD_DIR", str(upload_dir))
    return upload_dir


# ── Minimal valid image byte helpers ──────────────────────────────────────────

def _minimal_jpeg() -> bytes:
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000"
        "ffdb004300080606070605080707070909080a0c"
        "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
        "20242e2720222c231c1c2837292c30313434341f"
        "27393d38323c2e333432ffc0000b080001000101"
        "011100ffc4001f000001050101010101010000000"
        "0000000000102030405060708090a0bffc4003a10"
        "0003010101010101010101010101010101010203"
        "0405060708090a0b0c0d0e0f10111213ffda0008"
        "01010000003f00540400ffd9"
    )


def _minimal_png() -> bytes:
    import struct
    import zlib

    signature = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw_row = b"\x00\xff\xff\xff"
    idat_data = zlib.compress(raw_row)

    return signature + _chunk(b"IHDR", ihdr_data) + _chunk(b"IDAT", idat_data) + _chunk(b"IEND", b"")


def _minimal_gif() -> bytes:
    return (
        b"GIF89a"
        b"\x01\x00\x01\x00"
        b"\x00\x00\x00"
        b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00"
        b"\x02\x02\x44\x01\x00"
        b"\x3b"
    )


@pytest.fixture
def jpeg_bytes():
    return _minimal_jpeg()


@pytest.fixture
def png_bytes():
    return _minimal_png()


@pytest.fixture
def gif_bytes():
    return _minimal_gif()


# ── Seed-based fixtures for requirement tests ─────────────────────────────────

def _login_client(email: str, password: str):
    """Login and return authenticated client with bearer token."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    response = test_client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    test_client.headers["Authorization"] = f"Bearer {token}"
    app.dependency_overrides.clear()
    return test_client


@pytest.fixture
def seed_buyer(db_session):
    """Create buyer_a user and return their credentials."""
    from core.security import hash_password
    buyer = User(
        email="buyer@test.com",
        username="buyer_a",
        hashed_password=hash_password("BuyerPass123!"),
    )
    buyer.roles = [_ensure_role(db_session, "Buyer")]
    db_session.add(buyer)
    db_session.commit()
    db_session.refresh(buyer)
    return {
        "email": buyer.email,
        "password": "BuyerPass123!",
        "id": str(buyer.id),
    }


@pytest.fixture
def seed_seller(db_session):
    """Create seller_a user and return their credentials."""
    from core.security import hash_password
    seller = User(
        email="seller@test.com",
        username="seller_a",
        hashed_password=hash_password("SellerPass123!"),
    )
    seller.roles = [_ensure_role(db_session, "Seller")]
    db_session.add(seller)
    db_session.commit()
    db_session.refresh(seller)
    return {
        "email": seller.email,
        "password": "SellerPass123!",
        "id": str(seller.id),
    }


@pytest.fixture
def buyer_client(client, db_session, seed_buyer):
    """Return authenticated buyer client."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    response = test_client.post(
        "/auth/login",
        json={"email": seed_buyer["email"], "password": seed_buyer["password"]},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    test_client.headers["Authorization"] = f"Bearer {token}"
    app.dependency_overrides.clear()
    return test_client


@pytest.fixture
def seller_client(client, db_session, seed_seller):
    """Return authenticated seller client."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    response = test_client.post(
        "/auth/login",
        json={"email": seed_seller["email"], "password": seed_seller["password"]},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    test_client.headers["Authorization"] = f"Bearer {token}"
    app.dependency_overrides.clear()
    return test_client


@pytest.fixture
def buyer_a_client(buyer_client):
    """Alias for buyer_client."""
    return buyer_client


@pytest.fixture
def seller_a_client(seller_client):
    """Alias for seller_client."""
    return seller_client


@pytest.fixture
def active_product(db_session, seller_user):
    """Create and return an active product."""
    from models.models import Product
    product = Product(
        name="Active Product",
        description="A product that is visible to buyers.",
        price=29.99,
        stock=10,
        seller_id=seller_user.id,
        status="active",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return {
        "id": str(product.id),
        "price": float(product.price),
        "stock": product.stock,
        "status": "active",
        "seller_id": str(product.seller_id)
    }


@pytest.fixture
def delivered_order(db_session, buyer_user, seller_user, active_product):
    """Create and return a delivered order."""
    import uuid
    from models.models import Order, OrderItem, OrderStatus
    
    product_id = uuid.UUID(active_product["id"])
    order = Order(
        buyer_id=buyer_user.id,
        seller_id=seller_user.id,
        status=OrderStatus.delivered,
        total_amount=29.99,
        shipping_address="123 Test St, Porto, PT",
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product_id,
        quantity=1,
        unit_price=29.99,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(order)
    return {
        "id": str(order.id),
        "product_id": str(product_id),
        "total_amount": float(order.total_amount),
    }


@pytest.fixture
def buyer_b_order_id(db_session, seller_user):
    """Create buyer_b, seller_b, and their order."""
    from core.security import hash_password
    from models.models import Product, Order, OrderItem, OrderStatus

    buyer_b = User(
        email="buyerb@test.com",
        username="buyer_b",
        hashed_password=hash_password("BuyerPass123!"),
    )
    buyer_b.roles = [_ensure_role(db_session, "Buyer")]

    seller_b = User(
        email="sellerb@test.com",
        username="seller_b",
        hashed_password=hash_password("SellerPass123!"),
    )
    seller_b.roles = [_ensure_role(db_session, "Seller")]

    db_session.add(buyer_b)
    db_session.add(seller_b)
    db_session.flush()

    product = Product(
        name="Seller B Product",
        description="Seller B's product.",
        price=49.99,
        stock=5,
        seller_id=seller_b.id,
    )
    db_session.add(product)
    db_session.flush()

    order = Order(
        buyer_id=buyer_b.id,
        seller_id=seller_b.id,
        status=OrderStatus.pending,
        total_amount=49.99,
        shipping_address="456 Other St, Lisbon, PT",
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=1,
        unit_price=49.99,
    )
    db_session.add(item)
    db_session.commit()

    return str(order.id)


@pytest.fixture
def seller_b_product_id(db_session, seller_user):
    """Create seller_b and return their product ID."""
    from core.security import hash_password
    from models.models import Product

    seller_b = User(
        email="sellerb@test.com",
        username="seller_b",
        hashed_password=hash_password("SellerPass123!"),
    )
    seller_b.roles = [_ensure_role(db_session, "Seller")]
    db_session.add(seller_b)
    db_session.flush()

    product = Product(
        name="Seller B Product",
        description="Seller B's product.",
        price=49.99,
        stock=5,
        seller_id=seller_b.id,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    return str(product.id)
