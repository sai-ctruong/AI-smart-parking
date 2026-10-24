"""SQLAlchemy engine, sessions, and database connection check."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import MissingDatabaseConfiguration, get_settings


class Base(DeclarativeBase):
    """Metadata base for future SQLAlchemy models and Alembic revisions."""


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    """Create a reusable engine without opening a connection at API startup."""
    url = make_url(database_url)
    connect_args: dict[str, int] = {}
    if url.get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = 3
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@contextmanager
def session_scope(database_url: str) -> Iterator[Session]:
    """Close each session after use; callers control transaction commits."""
    with Session(get_engine(database_url)) as session:
        yield session


def get_db_session() -> Iterator[Session]:
    """FastAPI dependency for future database-backed endpoints."""
    with session_scope(get_settings().require_database_url()) as session:
        yield session


def check_database(database_url: str) -> None:
    """Execute a lightweight query to confirm the database is reachable."""
    with session_scope(database_url) as session:
        session.execute(text("SELECT 1"))


def main() -> int:
    """PowerShell-friendly connection smoke test: python -m app.db."""
    try:
        check_database(get_settings().require_database_url())
    except MissingDatabaseConfiguration as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError):
        print(
            "Database unavailable; verify PostgreSQL is running and "
            "DATABASE_URL is correct.",
            file=sys.stderr,
        )
        return 1
    print("Database connection OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
