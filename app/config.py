from functools import lru_cache

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="CONTACTS_",
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    app_name: str = "Contacts API"

    # Defaults to an in-process SQLite database so the app is self-contained.
    # Point this at a file (sqlite:///./contacts.db) or Postgres to persist data.
    database_url: str = "sqlite+pysqlite:///:memory:"

    # Insert a few sample contacts on startup. Handy for the in-memory default,
    # which starts empty on every boot.
    seed_data: bool = True

    host: str = "127.0.0.1"
    port: int = 8000
    sql_echo: bool = False

    image_endpoint: str | None = None
    image_api_key: SecretStr | None = None
    image_deployment: str = "gpt-image-2"
    image_api_version: str = "2025-04-01-preview"
    image_size: str = "1024x1024"
    image_quality: Literal["low", "medium", "high"] = "medium"
    image_output_format: Literal["png", "jpeg"] = "jpeg"
    image_timeout_seconds: int = Field(default=240, ge=1, le=600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
