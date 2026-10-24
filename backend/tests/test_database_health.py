from fastapi.testclient import TestClient

from app.config import DevelopmentSettings
from app.main import create_app


def test_health_without_database_check_stays_available() -> None:
    app = create_app(DevelopmentSettings(_env_file=None, database_url=None))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_readiness_reports_missing_configuration() -> None:
    app = create_app(DevelopmentSettings(_env_file=None, database_url=None))

    response = TestClient(app).get("/health?check_db=true")

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]


def test_database_readiness_checks_a_real_sql_connection() -> None:
    app = create_app(
        DevelopmentSettings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")
    )

    response = TestClient(app).get("/health?check_db=true")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ready"}


def test_database_readiness_reports_connection_failure(tmp_path) -> None:
    missing_directory = tmp_path / "missing" / "db.sqlite"
    app = create_app(
        DevelopmentSettings(
            _env_file=None, database_url=f"sqlite+pysqlite:///{missing_directory}"
        )
    )

    response = TestClient(app).get("/health?check_db=true")

    assert response.status_code == 503
    assert "Database unavailable" in response.json()["detail"]
    assert "missing" not in response.json()["detail"]


def test_cors_allows_only_configured_origin() -> None:
    app = create_app(
        DevelopmentSettings(_env_file=None, cors_origins=["http://localhost:5173"])
    )
    client = TestClient(app)

    allowed = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    blocked = client.options(
        "/health",
        headers={
            "Origin": "http://unlisted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in blocked.headers
