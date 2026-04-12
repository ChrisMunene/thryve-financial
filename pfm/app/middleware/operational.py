"""Operational ASGI middleware for request deadlines and body size limits."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import RequestDeadlineExceededError, RequestTooLargeProblem
from app.core.problems import problem_response


class RequestTimeoutMiddleware:
    def __init__(self, app: ASGIApp, timeout_seconds: int) -> None:
        self.app = app
        self._timeout_seconds = timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def wrapped_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, wrapped_send),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            if response_started:
                raise

            request = Request(scope, receive=receive)
            response = problem_response(request, RequestDeadlineExceededError.default())
            await response(scope, receive, send)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self._max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                parsed_length = int(content_length)
            except ValueError:
                parsed_length = None

            if parsed_length is not None and parsed_length > self._max_body_size:
                request = Request(scope, receive=receive)
                response = problem_response(request, RequestTooLargeProblem.default())
                await response(scope, receive, send)
                return

        total_bytes = 0

        async def limited_receive() -> Message:
            nonlocal total_bytes
            message = await receive()
            if message["type"] != "http.request":
                return message

            total_bytes += len(message.get("body", b""))
            if total_bytes > self._max_body_size:
                raise RequestTooLargeProblem.default()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLargeProblem:
            request = Request(scope, receive=receive)
            response = problem_response(request, RequestTooLargeProblem.default())
            await response(scope, receive, send)
