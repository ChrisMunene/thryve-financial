"""Global exception handlers and problem serialization."""

from __future__ import annotations

import traceback
from collections.abc import Sequence

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.exceptions import (
    InternalServerProblem,
    MalformedRequestError,
    ProblemException,
    RequestValidationProblem,
    UnsupportedMediaTypeError,
    problem_for_status,
)
from app.core.problems import problem_response
from app.core.responses import ProblemFieldError
from app.core.telemetry import get_metrics

logger = structlog.get_logger()

_BODY_METHODS = {"POST", "PUT", "PATCH"}
_FORM_MEDIA_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def _field_name(parts: Sequence[object]) -> str | None:
    if not parts:
        return None

    rendered: list[str] = []
    for part in parts:
        if isinstance(part, int):
            rendered.append(str(part))
        else:
            rendered.append(str(part))

    return ".".join(rendered)


def _problem_field_errors(exc: RequestValidationError) -> list[ProblemFieldError]:
    errors: list[ProblemFieldError] = []
    for item in exc.errors():
        loc = item.get("loc", ())
        if not loc:
            source = "unknown"
            remainder: Sequence[object] = ()
        else:
            raw_source = str(loc[0])
            source = (
                raw_source
                if raw_source in {"body", "query", "path", "header", "cookie"}
                else "unknown"
            )
            remainder = loc[1:]

        errors.append(
            ProblemFieldError(
                source=source,
                field=_field_name(remainder),
                code=str(item.get("type", "validation_error")),
                message=str(item.get("msg", "Invalid value")),
            )
        )
    return errors


def _request_has_body(request: Request) -> bool:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            return int(content_length) > 0
        except ValueError:
            return True

    return request.headers.get("transfer-encoding", "").lower() == "chunked"


def _content_type_is_supported(content_type: str | None) -> bool:
    if not content_type:
        return True

    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized == "application/json" or normalized.endswith("+json"):
        return True
    return normalized.startswith(_FORM_MEDIA_TYPES)


def _validation_problem_for_request(
    request: Request,
    exc: RequestValidationError,
) -> ProblemException:
    errors = _problem_field_errors(exc)
    raw_errors = exc.errors()

    if any(item.get("type") == "json_invalid" for item in raw_errors):
        return MalformedRequestError.default(errors=errors)

    body_related = any(item.get("loc", ("",))[0] == "body" for item in raw_errors)
    if (
        request.method.upper() in _BODY_METHODS
        and _request_has_body(request)
        and body_related
        and not _content_type_is_supported(request.headers.get("content-type"))
    ):
        return UnsupportedMediaTypeError.default()

    return RequestValidationProblem.from_errors(errors)


def _log_problem(
    request: Request,
    exc: ProblemException,
    *,
    traceback_text: str | None = None,
) -> None:
    upstream_context = {}
    if exc.upstream is not None:
        upstream_context = {
            "provider": exc.upstream.provider,
            "provider_code": exc.upstream.provider_code,
            "provider_request_id": exc.upstream.provider_request_id,
        }

    log_method = getattr(logger, exc.log_level, logger.error)
    payload = {
        "code": exc.code,
        "status": exc.status,
        "retryable": exc.retryable,
        "path": request.url.path,
        "method": request.method,
        **upstream_context,
        **exc.extra_log_context,
    }
    if traceback_text is not None:
        payload["traceback"] = traceback_text

    log_method("api.problem", **payload)
    get_metrics().record_api_error(
        code=exc.code,
        status_code=exc.status,
        retryable=exc.retryable,
    )


def register_error_handlers(app: FastAPI, debug: bool = False) -> None:
    """Register problem-details based exception handlers on the FastAPI app."""

    @app.exception_handler(ProblemException)
    async def handle_problem_exception(request: Request, exc: ProblemException) -> Response:
        _log_problem(request, exc)
        return problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> Response:
        problem = _validation_problem_for_request(request, exc)
        _log_problem(request, problem)
        return problem_response(request, problem)

    @app.exception_handler(StarletteHTTPException)
    async def handle_starlette_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> Response:
        problem = problem_for_status(
            exc.status_code,
            detail=str(exc.detail) if isinstance(exc.detail, str) else None,
            headers=exc.headers,
        )
        _log_problem(request, problem)
        return problem_response(request, problem)

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> Response:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        problem = InternalServerProblem.default()
        _log_problem(request, problem, traceback_text=tb)
        return problem_response(request, problem)
