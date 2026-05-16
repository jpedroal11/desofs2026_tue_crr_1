import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys
import os

# Ensure the marketplace directory is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from core.dependencies import get_db, get_current_user
from models.models import Base, User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    # clean db for each test
    for table in reversed(Base.metadata.sorted_tables):
        with engine.connect() as conn:
            conn.execute(table.delete())
            conn.commit()

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def seller_user(db_session):
    user = User(email="seller@example.com", username="seller", hashed_password="hashed_password")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

@pytest.fixture
def buyer_user(db_session):
    user = User(email="buyer@example.com", username="buyer", hashed_password="hashed_password")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


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
    """Return bytes for the smallest valid JPEG (a 1x1 white pixel)."""
    import struct
    # Minimal JFIF: SOI + APP0 + DQT + SOF0 + DHT + SOS + image data + EOI
    # This is the smallest valid JPEG that most parsers accept.
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
    """Return bytes for a minimal valid 1x1 white PNG."""
    import struct
    import zlib

    signature = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit RGB
    raw_row = b"\x00\xff\xff\xff"  # filter byte + RGB
    idat_data = zlib.compress(raw_row)

    return signature + _chunk(b"IHDR", ihdr_data) + _chunk(b"IDAT", idat_data) + _chunk(b"IEND", b"")


def _minimal_gif() -> bytes:
    """Return bytes for a minimal valid GIF89a."""
    return (
        b"GIF89a"  # Header
        b"\x01\x00\x01\x00"  # 1x1
        b"\x00\x00\x00"  # No GCT
        b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00"  # Image descriptor
        b"\x02\x02\x44\x01\x00"  # LZW min code size + data
        b"\x3b"  # Trailer
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
