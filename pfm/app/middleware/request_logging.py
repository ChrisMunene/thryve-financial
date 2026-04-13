"""Canonical request-completion logging middleware."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger("app.http")

_DEFAULT_HEALTHCHECK_PATHS = frozenset(
    {
        "/api/v1/health",
        "/api/v1/health/ready",
    }
)


def _route_template(scope: Scope) -> str | None:
    route = scope.get("route")
    if route is None:
        return None
    return getattr(route, "path", None) or getattr(route, "path_format", None)


class RequestLoggingMiddleware:
    """Emit exactly one canonical request-completion event per HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool = True,
        log_healthcheck_requests: bool = False,
        log_options_requests: bool = False,
        healthcheck_paths: Iterable[str] = _DEFAULT_HEALTHCHECK_PATHS,
    ) -> None:
        self.app = app
        self._enabled = enabled
        self._log_healthcheck_requests = log_healthcheck_requests
        self._log_options_requests = log_options_requests
        self._healthcheck_paths = frozenset(healthcheck_paths)

    def _should_skip(self, scope: Scope) -> bool:
        if not self._enabled:
            return True

        method = scope.get("method", "").upper()
        path = scope.get("path", "")

        if method == "OPTIONS" and not self._log_options_requests:
            return True

        if path in self._healthcheck_paths and not self._log_healthcheck_requests:
            return True

        return False

    @staticmethod
    def _emit(scope: Scope, status_code: int, duration_ms: int) -> None:
        payload: dict[str, Any] = {
            "method": scope.get("method"),
            "path": scope.get("path"),
            "status_code": status_code,
            "duration_ms": duration_ms,
        }
        route = _route_template(scope)
        if route is not None:
            payload["route"] = route

        logger.info("request.completed", **payload)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._should_skip(scope):
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        status_code = 500
        completed = False

        async def send_with_logging(message: Message) -> None:
            nonlocal completed, status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and not completed
            ):
                completed = True
                duration_ms = round((time.perf_counter() - started_at) * 1000)
                self._emit(scope, status_code, duration_ms)

            await send(message)

        try:
            await self.app(scope, receive, send_with_logging)
        except Exception:
            if not completed:
                completed = True
                duration_ms = round((time.perf_counter() - started_at) * 1000)
                self._emit(scope, status_code, duration_ms)
            raise
