"""
Operational middleware.

Applies request timeout and request body size limits to every request.
"""

import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.context import get_correlation_id
from app.core.exceptions import RequestTooLargeError
from app.core.responses import error_response


def _error_json(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_response(
            code=code,
            message=message,
            request_id=get_correlation_id(),
        ).model_dump(),
    )


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, timeout_seconds: int) -> None:
        super().__init__(app)
        self._timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await asyncio.wait_for(call_next(request), timeout=self._timeout_seconds)
        except TimeoutError:
            return _error_json(
                status_code=504,
                code="REQUEST_TIMEOUT",
                message="Request processing timed out",
            )


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_size: int) -> None:
        super().__init__(app)
        self._max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                parsed_length = int(content_length)
            except ValueError:
                parsed_length = None

            if parsed_length is not None and parsed_length > self._max_body_size:
                return _error_json(
                    status_code=413,
                    code="REQUEST_TOO_LARGE",
                    message="Request body exceeds the maximum allowed size",
                )

        original_receive = request._receive
        total_bytes = 0

        async def receive() -> dict[str, object]:
            nonlocal total_bytes
            message = await original_receive()

            if message["type"] == "http.request":
                body = message.get("body", b"")
                total_bytes += len(body)
                if total_bytes > self._max_body_size:
                    raise RequestTooLargeError()

            return message

        request._receive = receive

        try:
            return await call_next(request)
        except RequestTooLargeError:
            return _error_json(
                status_code=413,
                code="REQUEST_TOO_LARGE",
                message="Request body exceeds the maximum allowed size",
            )
