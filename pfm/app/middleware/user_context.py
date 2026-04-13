"""
User context middleware.

Ensures request-scoped analytics identity does not leak across requests and
hydrates anonymous identity from inbound request headers.
"""

import re

import structlog
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.context import (
    clear_current_anonymous_id,
    clear_current_user_id,
    set_current_anonymous_id,
)

logger = structlog.get_logger()
ANONYMOUS_ID_HEADER = "X-Anonymous-ID"
_ANONYMOUS_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class UserContextMiddleware:
    """Reset request-scoped identity context before and after each request."""

    def __init__(self, app: ASGIApp, anonymous_id_header: str = ANONYMOUS_ID_HEADER) -> None:
        self.app = app
        self._anonymous_id_header = anonymous_id_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        clear_current_anonymous_id()
        clear_current_user_id()
        try:
            raw_anonymous_id = Headers(scope=scope).get(self._anonymous_id_header)
            if raw_anonymous_id:
                if _ANONYMOUS_ID_PATTERN.fullmatch(raw_anonymous_id):
                    set_current_anonymous_id(raw_anonymous_id)
                    scope.setdefault("state", {})["anonymous_id"] = raw_anonymous_id
                else:
                    logger.warning(
                        "analytics.invalid_anonymous_id",
                        header_name=self._anonymous_id_header,
                        length=len(raw_anonymous_id),
                    )
            await self.app(scope, receive, send)
        finally:
            clear_current_anonymous_id()
            clear_current_user_id()
