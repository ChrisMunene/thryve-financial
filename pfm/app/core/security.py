"""Security headers middleware."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add standard security headers to every HTTP response."""

    def __init__(self, app: ASGIApp, is_production: bool = False) -> None:
        self.app = app
        self._is_production = is_production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                if self._is_production:
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_with_headers)
