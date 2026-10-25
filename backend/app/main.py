"""ASGI application entry point."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.auth import ApiError
from app.auth import router as auth_router
from app.config import AppSettings, MissingDatabaseConfiguration, get_settings
from app.configuration import router as configuration_router
from app.db import check_database


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Construct the API without requiring PostgreSQL to be online."""
    configured = settings if settings is not None else get_settings()
    api = FastAPI(title="Smart Parking Management System API")
    api.state.settings = configured
    api.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    @api.middleware("http")
    async def assign_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @api.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else {}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": {},
                    "request_id": request.state.request_id,
                }
            },
            headers=headers,
        )

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/api/v1/"):
            return JSONResponse(status_code=422, content={"detail": exc.errors()})
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request",
                    "details": {},
                    "request_id": request.state.request_id,
                }
            },
        )

    api.include_router(auth_router)
    api.include_router(configuration_router)

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
