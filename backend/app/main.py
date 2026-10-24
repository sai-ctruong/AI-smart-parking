"""ASGI application entry point."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.config import AppSettings, MissingDatabaseConfiguration, get_settings
from app.db import check_database


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Construct the API without requiring PostgreSQL to be online."""
    configured = settings if settings is not None else get_settings()
    api = FastAPI(title="Smart Parking Management System API")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @api.get("/health")
    def health(check_db: bool = False) -> dict[str, str]:
        """Report process liveness and optionally verify database readiness."""
        if not check_db:
            return {"status": "ok"}
        try:
            check_database(configured.require_database_url())
        except MissingDatabaseConfiguration as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (SQLAlchemyError, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Database unavailable; verify PostgreSQL is running and "
                    "DATABASE_URL is correct."
                ),
            ) from exc
        return {"status": "ok", "database": "ready"}

    return api


app = create_app()
