"""Environment-specific API settings."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class MissingDatabaseConfiguration(ValueError):
    """Raised when a database operation has no connection URL."""


class BaseAppSettings(BaseSettings):
    database_url: str | None = None
    cors_origins: list[str] = Field(default_factory=list)
    auth_secret_key: SecretStr | None = None
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    image_storage_root: Path | None = None
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_image_pixels: int = Field(default=20_000_000, ge=4)
    stale_after_seconds: int = Field(default=300, ge=1)
    parking_model_checkpoint: Path | None = None
    parking_confidence_threshold: float = Field(default=0.7, ge=0.5, le=1)
    parking_inference_batch_size: int = Field(default=32, ge=1)
    parking_inference_device: Literal["auto", "cpu", "cuda"] = "auto"

    model_config = SettingsConfigDict(extra="ignore")

    @field_validator("database_url", mode="before")
    @classmethod
    def blank_url_is_missing(cls, value: str | None) -> str | None:
        return value.strip() or None if isinstance(value, str) else value

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise MissingDatabaseConfiguration(
                "DATABASE_URL is missing; set it before checking database readiness."
            )
        return self.database_url

    def require_auth_secret(self) -> str:
        if self.auth_secret_key is None:
            raise ValueError("AUTH_SECRET_KEY is required for authentication")
        secret = self.auth_secret_key.get_secret_value()
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("AUTH_SECRET_KEY must contain at least 32 bytes")
        return secret


class DevelopmentSettings(BaseAppSettings):
    app_env: Literal["development"] = "development"
    image_storage_root: Path = (
        Path(__file__).resolve().parents[1] / "data" / "snapshots"
    )
    model_config = SettingsConfigDict(env_file=LOCAL_ENV_FILE, extra="ignore")


class ProductionSettings(BaseAppSettings):
    app_env: Literal["production"] = "production"
    model_config = SettingsConfigDict(extra="ignore")

    @model_validator(mode="after")
    def require_production_database(self) -> "ProductionSettings":
        if self.database_url is None:
            raise ValueError("DATABASE_URL is required when APP_ENV=production")
        self.require_auth_secret()
        if self.image_storage_root is None or not self.image_storage_root.is_absolute():
            raise ValueError(
                "IMAGE_STORAGE_ROOT must be an absolute path when APP_ENV=production"
            )
        return self


AppSettings = DevelopmentSettings | ProductionSettings


def get_settings() -> AppSettings:
    """Load a local .env only in development; production uses process variables."""
    app_env = os.environ.get("APP_ENV", "development").lower()
    if app_env == "development":
        return DevelopmentSettings()
    if app_env == "production":
        return ProductionSettings()
    raise ValueError("APP_ENV must be 'development' or 'production'")
