"""Ensure every HTTP response carries exactly one X-Request-ID header."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import get_correlation_id


class ResponseRequestIdMiddleware:
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self._header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                request_id = get_correlation_id()
                if request_id:
                    headers = MutableHeaders(raw=list(message.get("headers", [])))
                    if self._header_name in headers:
                        del headers[self._header_name]
                    headers[self._header_name] = request_id
                    message["headers"] = headers.raw
            await send(message)

        await self.app(scope, receive, send_with_request_id)
