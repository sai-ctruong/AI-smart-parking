import pytest
from pydantic import ValidationError

from app.config import DevelopmentSettings, ProductionSettings, get_settings


def test_development_reads_database_and_cors_allowlist_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/parking\n"
        'CORS_ORIGINS=["http://localhost:5173"]\n',
        encoding="utf-8",
    )

    settings = DevelopmentSettings(_env_file=env_file)

    assert settings.database_url == (
        "postgresql+psycopg://user:pass@localhost:5432/parking"
    )
    assert settings.cors_origins == ["http://localhost:5173"]


def test_production_requires_database_url_from_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        get_settings()


def test_production_requires_absolute_private_image_root() -> None:
    with pytest.raises(ValidationError, match="IMAGE_STORAGE_ROOT"):
        ProductionSettings(
            _env_file=None,
            database_url="postgresql+psycopg://user:pass@localhost:5432/parking",
            auth_secret_key="test-only-secret-with-at-least-32-bytes",
            image_storage_root="relative/images",
        )
