"""Authentication and role boundaries on a disposable migrated database."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from alembic import command
from app.bootstrap_admin import bootstrap_admin
from app.bootstrap_admin import main as bootstrap_main
from app.config import DevelopmentSettings, ProductionSettings
from app.main import create_app
from app.models import AuditLog, User

SECRET = "test-only-secret-key-with-at-least-32-bytes"
ADMIN_PASSWORD = "Correct-horse-admin-2026"
OPERATOR_PASSWORD = "Correct-horse-operator-2026"


@pytest.fixture
def auth_context(tmp_path: Path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'auth.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    engine = create_engine(database_url)
    with Session(engine) as session:
        admin = bootstrap_admin(session, "admin", ADMIN_PASSWORD)
        session.commit()
        admin_id = admin.id
    settings = DevelopmentSettings(
        _env_file=None,
        database_url=database_url,
        auth_secret_key=SECRET,
        cors_origins=["http://localhost:5173"],
    )
    with TestClient(create_app(settings)) as client:
        yield client, engine, admin_id
    engine.dispose()


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_operator(client: TestClient, admin_token: str):
    return client.post(
        "/api/v1/users",
        headers=_auth(admin_token),
        json={
            "username": "operator1",
            "password": OPERATOR_PASSWORD,
            "role": "operator",
        },
    )


def test_valid_login_returns_short_lived_token_and_safe_identity(auth_context) -> None:
    client, engine, admin_id = auth_context
    response = _login(client, "admin", ADMIN_PASSWORD)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 900
    assert "password" not in str(response.json()).lower()
    token = response.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json() == {
        "id": str(admin_id),
        "username": "admin",
        "role": "admin",
        "is_active": True,
    }
    with Session(engine) as session:
        stored = session.scalar(select(User).where(User.id == admin_id))
        assert stored.password_hash != ADMIN_PASSWORD
        assert stored.password_hash.startswith("$argon2id$")
        assert (
            session.scalar(
                select(AuditLog).where(AuditLog.action == "auth.login")
            ).actor_id
            == admin_id
        )


def test_bad_credentials_share_one_unauthorized_shape(auth_context) -> None:
    client, _, _ = auth_context
    wrong_user = _login(client, "missing", "not-the-password")
    wrong_password = _login(client, "admin", "not-the-password")

    for response in (wrong_user, wrong_password):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
        assert response.json()["error"]["details"] == {}
        assert response.json()["error"]["request_id"]
    assert (
        wrong_user.json()["error"]["message"]
        == wrong_password.json()["error"]["message"]
    )


def test_missing_expired_and_invalid_tokens_are_rejected(auth_context) -> None:
    client, _, admin_id = auth_context
    claims = {
        "sub": str(admin_id),
        "ver": 0,
        "iss": "smart-parking-api",
        "aud": "smart-parking",
        "iat": datetime.now(timezone.utc) - timedelta(hours=1),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    expired = jwt.encode(claims, SECRET, algorithm="HS256")
    wrong_audience = jwt.encode(
        {
            **claims,
            "aud": "unrelated-app",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
        },
        SECRET,
        algorithm="HS256",
    )
    missing_expiry = jwt.encode(
        {key: value for key, value in claims.items() if key != "exp"},
        SECRET,
        algorithm="HS256",
    )
    for headers in (
        {},
        _auth(expired),
        _auth(wrong_audience),
        _auth(missing_expiry),
        _auth("not-a-jwt"),
    ):
        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_operator_cannot_manage_users_and_role_is_rechecked(auth_context) -> None:
    client, engine, _ = auth_context
    admin_token = _login(client, "admin", ADMIN_PASSWORD).json()["access_token"]
    created = _create_operator(client, admin_token)
    assert created.status_code == 201
    assert set(created.json()) == {"id", "username", "role", "is_active"}
    operator_token = _login(client, "operator1", OPERATOR_PASSWORD).json()[
        "access_token"
    ]
    denied = client.post(
        "/api/v1/users",
        headers=_auth(operator_token),
        json={"username": "newuser", "password": OPERATOR_PASSWORD, "role": "admin"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    assert client.get("/api/v1/users", headers=_auth(operator_token)).status_code == 403
    assert client.get("/api/v1/users").status_code == 401
    assert (
        client.patch(
            f"/api/v1/users/{created.json()['id']}",
            headers=_auth(operator_token),
            json={"role": "admin"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/users/{created.json()['id']}/password",
            headers=_auth(operator_token),
            json={"password": "Cannot-reset-this-password"},
        ).status_code
        == 403
    )

    with Session(engine) as session:
        operator = session.scalar(select(User).where(User.username == "operator1"))
        operator.role = "admin"
        session.commit()
    assert client.get("/api/v1/users", headers=_auth(operator_token)).status_code == 200


def test_admin_disables_operator_and_resets_password(auth_context) -> None:
    client, engine, _ = auth_context
    admin_token = _login(client, "admin", ADMIN_PASSWORD).json()["access_token"]
    created = _create_operator(client, admin_token)
    user_id = created.json()["id"]
    operator_token = _login(client, "operator1", OPERATOR_PASSWORD).json()[
        "access_token"
    ]
    new_password = "A-new-operator-password-2026"
    reset = client.post(
        f"/api/v1/users/{user_id}/password",
        headers=_auth(admin_token),
        json={"password": new_password},
    )
    assert reset.status_code == 200
    assert "password" not in str(reset.json()).lower()
    assert (
        client.get("/api/v1/auth/me", headers=_auth(operator_token)).status_code == 401
    )
    assert _login(client, "operator1", OPERATOR_PASSWORD).status_code == 401
    assert _login(client, "operator1", new_password).status_code == 200
    disabled = client.patch(
        f"/api/v1/users/{user_id}",
        headers=_auth(admin_token),
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert (
        client.get("/api/v1/auth/me", headers=_auth(operator_token)).status_code == 401
    )
    assert _login(client, "operator1", new_password).status_code == 401
    with Session(engine) as session:
        assert session.scalar(
            select(AuditLog).where(AuditLog.action == "user.updated")
        ).actor_id


def test_bootstrap_refuses_second_initial_admin(auth_context) -> None:
    _, engine, _ = auth_context
    with Session(engine) as session:
        with pytest.raises(ValueError, match="already"):
            bootstrap_admin(session, "other-admin", ADMIN_PASSWORD)


def test_last_active_admin_cannot_disable_self(auth_context) -> None:
    client, _, admin_id = auth_context
    token = _login(client, "admin", ADMIN_PASSWORD).json()["access_token"]
    response = client.patch(
        f"/api/v1/users/{admin_id}",
        headers=_auth(token),
        json={"is_active": False},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert client.get("/api/v1/auth/me", headers=_auth(token)).status_code == 200


def test_duplicate_username_and_invalid_user_body(auth_context) -> None:
    client, _, _ = auth_context
    token = _login(client, "admin", ADMIN_PASSWORD).json()["access_token"]
    assert _create_operator(client, token).status_code == 201
    assert _create_operator(client, token).status_code == 409
    invalid = client.post(
        "/api/v1/users",
        headers=_auth(token),
        json={
            "username": "operator2",
            "password": "short",
            "role": "operator",
            "password_hash": "attacker-supplied",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "short" not in str(invalid.json())


def test_bootstrap_cli_uses_prompt_and_refuses_second_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'bootstrap.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    answers = iter([ADMIN_PASSWORD, ADMIN_PASSWORD, ADMIN_PASSWORD, ADMIN_PASSWORD])
    monkeypatch.setattr(
        "app.bootstrap_admin.getpass.getpass", lambda _prompt: next(answers)
    )

    assert bootstrap_main(["--username", "firstadmin"]) == 0
    assert bootstrap_main(["--username", "anotheradmin"]) == 1
    output = capsys.readouterr()
    assert ADMIN_PASSWORD not in output.out + output.err
    engine = create_engine(database_url)
    with Session(engine) as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].password_hash.startswith("$argon2id$")
    engine.dispose()


def test_production_needs_a_nontrivial_auth_secret() -> None:
    with pytest.raises(ValueError, match="AUTH_SECRET_KEY"):
        ProductionSettings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")


def test_cors_allows_configured_login_post(auth_context) -> None:
    client, _, _ = auth_context
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
