"""Application settings loaded from environment variables.

SECRET_KEY and DATABASE_URL have no defaults — the app refuses to start if
they are not set. This prevents an accidental production deployment with a
known-default key.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Application
    app_env: str = "development"
    secret_key: str  # required
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Database
    database_url: str  # required

    # Uploads
    upload_dir: str = "uploads"

    # CORS — comma-separated list of origins (e.g. "http://localhost:3000")
    cors_allow_origins: str = ""


@lru_cache()
def get_settings() -> Settings:
    return Settings()
