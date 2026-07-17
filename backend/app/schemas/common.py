from typing import Any

from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None
