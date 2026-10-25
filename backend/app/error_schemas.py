"""Shared OpenAPI schema for the versioned API error envelope."""

from typing import Any

from pydantic import BaseModel


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any]
    request_id: str


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody
