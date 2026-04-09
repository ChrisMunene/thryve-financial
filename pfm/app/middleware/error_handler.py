"""
Global exception handler.

Catches AppException subclasses and unhandled exceptions.
Returns standardized error envelope. Logs with full context.
In dev: includes stack trace in response. In prod: error code + message only.
"""

import traceback

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.context import get_correlation_id
from app.core.exceptions import AppException
from app.core.responses import error_response

logger = structlog.get_logger()


def register_error_handlers(app: FastAPI, debug: bool = False) -> None:
    """Register global exception handlers on the FastAPI app."""

    def _response_headers(correlation_id: str | None) -> dict[str, str]:
        if not correlation_id:
            return {}
        return {"X-Request-ID": correlation_id}

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        correlation_id = get_correlation_id()

        log_method = logger.warning if exc.status_code < 500 else logger.error
        log_method(
            exc.message,
            error_code=exc.error_code,
            status_code=exc.status_code,
            path=request.url.path,
            method=request.method,
            correlation_id=correlation_id,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(
                code=exc.error_code,
                message=exc.message,
                details=exc.details,
                request_id=correlation_id,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = get_correlation_id()
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)

        logger.error(
            "Unhandled exception",
            error=str(exc),
            error_type=type(exc).__name__,
            path=request.url.path,
            method=request.method,
            correlation_id=correlation_id,
            traceback="".join(tb),
        )

        details = ["".join(tb)] if debug else None

        return JSONResponse(
            status_code=500,
            content=error_response(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred" if not debug else str(exc),
                details=details,
                request_id=correlation_id,
            ).model_dump(),
            headers=_response_headers(correlation_id),
        )
