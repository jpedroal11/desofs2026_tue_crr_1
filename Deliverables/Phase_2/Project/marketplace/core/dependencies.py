"""Database engine + session.

Auth helpers (JWT, bcrypt, current-user resolution) used to live here. They
have moved to:
  - core.security    — password hashing + JWT encode/decode
  - middleware.auth  — get_current_user, role-based dependencies

Existing teammate imports of ``get_db``/``get_current_user`` from this module
still work via the re-exports at the bottom.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import get_settings

settings = get_settings()

if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
