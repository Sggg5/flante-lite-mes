from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def error_payload(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details,
        "request_id": getattr(request.state, "request_id", None),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = exc.errors()
        for item in details:
            if "ctx" in item:
                item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        return JSONResponse(
            status_code=422,
            content=error_payload(request, "VALIDATION_ERROR", "请求参数校验失败", details),
        )
