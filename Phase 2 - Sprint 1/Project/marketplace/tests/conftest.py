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
    user = User(email="seller@example.com", username="seller", hashed_password="hashed_password", is_seller=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

@pytest.fixture
def buyer_user(db_session):
    user = User(email="buyer@example.com", username="buyer", hashed_password="hashed_password", is_seller=False)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
