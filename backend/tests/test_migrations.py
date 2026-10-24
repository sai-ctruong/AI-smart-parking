from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_initial_migration_creates_version_table(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "migration-smoke.sqlite"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    try:
        assert inspect(engine).has_table("alembic_version")
    finally:
        engine.dispose()
