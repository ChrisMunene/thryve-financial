"""
User context middleware.

Ensures request-scoped user context used for observability does not leak
across requests.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.context import clear_current_user_id


class UserContextMiddleware:
    """Reset request-scoped user context before and after each request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        clear_current_user_id()
        try:
            await self.app(scope, receive, send)
        finally:
            clear_current_user_id()
