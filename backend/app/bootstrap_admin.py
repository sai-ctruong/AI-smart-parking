"""Local, one-time Admin creation without a default or CLI password."""

import argparse
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import UserCreate, hash_password
from app.config import MissingDatabaseConfiguration, get_settings
from app.db import session_scope
from app.models import AuditLog, User


def bootstrap_admin(session: Session, username: str, password: str) -> User:
    """Create the first account only; caller owns commit/rollback."""
    if session.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Initial account already exists; use an Admin account")
    try:
        data = UserCreate(username=username, password=password, role="admin")
    except ValidationError as exc:
        raise ValueError("Invalid bootstrap username or password policy") from exc
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role="admin",
    )
    session.add(user)
    session.flush()
    session.add(
        AuditLog(
            actor_id=None,
            action="admin.bootstrapped",
            target_type="user",
            target_id=user.id,
            details={"source": "local_cli"},
        )
    )
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the first Admin account")
    parser.add_argument("--username", required=True, help="Admin username")
    args = parser.parse_args(argv)
    password = getpass.getpass("New Admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        with session_scope(get_settings().require_database_url()) as session:
            bootstrap_admin(session, args.username, password)
            session.commit()
    except (MissingDatabaseConfiguration, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Bootstrap failed; check database readiness and migrations.",
            file=sys.stderr,
        )
        return 1
    print("Initial Admin account created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
