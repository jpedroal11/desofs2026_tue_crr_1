"""Database engine + session.

Auth helpers (JWT, bcrypt, current-user resolution) used to live here. They
have moved to:
  - core.security    — password hashing + JWT encode/decode
  - middleware.auth  — get_current_user, role-based dependencies

Existing teammate imports of ``get_db``/``get_current_user`` from this module
still work via the re-exports at the bottom.
"""

from typing import Generator

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import get_settings

settings = get_settings()


def enforce_db_tls(db_url: str, force: bool = False) -> str:
    """Enforces TLS policy for database connection string.

    SQLite connections are bypassed.
    For other databases, it verifies that no insecure sslmodes are configured,
    and forces sslmode=require if not specified.
    """
    if db_url.startswith("sqlite") or not force:
        return db_url

    parsed = urlparse(db_url)
    query_params = dict(parse_qsl(parsed.query))

    # Check for lower-cased sslmode keys
    sslmode_key = next((k for k in query_params if k.lower() == "sslmode"), None)

    if sslmode_key:
        sslmode_val = query_params[sslmode_key].lower()
        if sslmode_val in ("disable", "allow", "prefer"):
            raise ValueError(
                f"Insecure sslmode='{sslmode_val}' fallback parameter is not allowed. "
                "Hard-enforced security policy requires TLS (e.g. sslmode=require, verify-ca, verify-full)."
            )
        if sslmode_val not in ("require", "verify-ca", "verify-full"):
            query_params[sslmode_key] = "require"
    else:
        # Default to require if not specified
        query_params["sslmode"] = "require"

    # Reconstruct the connection URL
    new_query = urlencode(query_params)
    return urlunparse(parsed._replace(query=new_query))


# Validate and secure connection string on startup (only enforced in production)
database_url_secured = enforce_db_tls(
    settings.database_url,
    force=(settings.app_env.lower() == "production")
)

if database_url_secured.startswith("sqlite"):
    engine = create_engine(
        database_url_secured,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(
        database_url_secured,
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
