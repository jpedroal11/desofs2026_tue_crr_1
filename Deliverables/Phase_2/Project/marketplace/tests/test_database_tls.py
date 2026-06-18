import importlib
import os
from unittest.mock import MagicMock, patch
import pytest

from core.config import get_settings
import core.dependencies
from core.dependencies import enforce_db_tls


@pytest.fixture(autouse=True)
def cleanup_settings_and_dependencies():
    """Ensure that the settings cache and dependencies module are restored after each test."""
    import core.dependencies

    # Save original references
    orig_attrs = {
        "engine": getattr(core.dependencies, "engine", None),
        "SessionLocal": getattr(core.dependencies, "SessionLocal", None),
        "get_db": getattr(core.dependencies, "get_db", None),
        "database_url_secured": getattr(core.dependencies, "database_url_secured", None),
    }

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

    # Restore original references in the module namespace
    for name, val in orig_attrs.items():
        if val is not None:
            setattr(core.dependencies, name, val)


def test_enforce_db_tls_sqlite():
    """Test that SQLite database URLs are bypassed and returned unchanged."""
    sqlite_url = "sqlite:///./dev.db"
    assert enforce_db_tls(sqlite_url, force=True) == sqlite_url

    sqlite_memory = "sqlite:///:memory:"
    assert enforce_db_tls(sqlite_memory, force=True) == sqlite_memory


def test_enforce_db_tls_postgres_appends_sslmode():
    """Test that PostgreSQL URLs without sslmode automatically get sslmode=require when forced."""
    db_url = "postgresql+psycopg2://user:pass@localhost:5432/db"
    secured = enforce_db_tls(db_url, force=True)
    assert "sslmode=require" in secured

    # Bypassed when not forced
    not_secured = enforce_db_tls(db_url, force=False)
    assert "sslmode" not in not_secured


def test_enforce_db_tls_postgres_preserves_safe_sslmode():
    """Test that safe sslmodes (require, verify-ca, verify-full) are preserved when forced."""
    for mode in ("require", "verify-ca", "verify-full"):
        db_url = f"postgresql+psycopg2://user:pass@localhost:5432/db?sslmode={mode}"
        secured = enforce_db_tls(db_url, force=True)
        assert f"sslmode={mode}" in secured

        # Mixed casing test
        db_url_caps = f"postgresql+psycopg2://user:pass@localhost:5432/db?SSLMode={mode.upper()}"
        secured_caps = enforce_db_tls(db_url_caps, force=True)
        assert f"sslmode={mode}" in secured_caps.lower()


def test_enforce_db_tls_postgres_rejects_insecure_sslmode():
    """Test that insecure/fallback sslmodes (disable, allow, prefer) raise ValueError when forced."""
    for mode in ("disable", "allow", "prefer"):
        db_url = f"postgresql+psycopg2://user:pass@localhost:5432/db?sslmode={mode}"
        with pytest.raises(ValueError) as excinfo:
            enforce_db_tls(db_url, force=True)
        assert "Insecure sslmode" in str(excinfo.value)

        # Caps test
        db_url_caps = f"postgresql+psycopg2://user:pass@localhost:5432/db?SSLMODE={mode.upper()}"
        with pytest.raises(ValueError) as excinfo:
            enforce_db_tls(db_url_caps, force=True)
        assert "Insecure sslmode" in str(excinfo.value)


def test_bootstrap_aborts_on_insecure_sslmode():
    """Validate that the system aborts the bootstrap sequence if a non-TLS fallback is configured in production."""
    for mode in ("disable", "allow", "prefer"):
        with patch.dict("os.environ", {
            "DATABASE_URL": f"postgresql+psycopg2://user:pass@localhost:5432/db?sslmode={mode}",
            "SECRET_KEY": "test-secret-key-at-least-32-bytes-long",
            "APP_ENV": "production"
        }):
            get_settings.cache_clear()
            with pytest.raises(ValueError) as excinfo:
                importlib.reload(core.dependencies)
            assert "Insecure sslmode" in str(excinfo.value)


def test_active_connection_parameters_passed_to_driver():
    """Assert that the connection parameters sent to the psycopg2 driver strictly include sslmode=require in production."""
    # We patch psycopg2.connect to intercept the connection initialization.
    with patch("psycopg2.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        mock_connect.return_value = mock_conn

        # Use a postgres connection string to trigger postgres setup
        db_url = "postgresql+psycopg2://user:password@localhost:5432/dbname"
        with patch.dict("os.environ", {
            "DATABASE_URL": db_url,
            "SECRET_KEY": "test-secret-key-at-least-32-bytes-long",
            "APP_ENV": "production"
        }):
            get_settings.cache_clear()
            # Reload module to trigger engine creation with our patched environment
            importlib.reload(core.dependencies)

            # Attempt a connection using the engine to trigger the driver connect call
            try:
                conn = core.dependencies.engine.connect()
                conn.close()
            except Exception:
                pass

            # Verify that psycopg2.connect was called with sslmode=require
            assert mock_connect.called
            args, kwargs = mock_connect.call_args
            
            # The parameter could be passed in keyword args (psycopg2.connect(..., sslmode="require"))
            # or parsed within the DSN string argument.
            sslmode_found = False
            if "sslmode" in kwargs:
                assert kwargs["sslmode"] in ("require", "verify-ca", "verify-full")
                sslmode_found = True
            elif len(args) > 0 and isinstance(args[0], str):
                dsn_str = args[0]
                assert "sslmode=require" in dsn_str or "sslmode=verify-ca" in dsn_str or "sslmode=verify-full" in dsn_str
                sslmode_found = True

            assert sslmode_found, f"sslmode parameter not found in connection arguments. args: {args}, kwargs: {kwargs}"
