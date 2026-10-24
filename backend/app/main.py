"""ASGI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="Smart Parking Management System API")


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the API process is available."""
    return {"status": "ok"}
