"""
Request context via contextvars.

Stores correlation ID per request, accessible anywhere in the async call chain.
Used by: structlog processors, error handler, outbound HTTP clients, Celery tasks.
"""

import uuid
from contextvars import ContextVar

from asgi_correlation_id import correlation_id as _http_correlation_id

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_correlation_id() -> str | None:
    return _http_correlation_id.get()


def set_correlation_id(value: str) -> None:
    _http_correlation_id.set(value)


def generate_correlation_id() -> str:
    cid = str(uuid.uuid4())
    _http_correlation_id.set(cid)
    return cid


def clear_correlation_id() -> None:
    _http_correlation_id.set(None)


def get_current_user_id() -> str | None:
    return _current_user_id.get()


def set_current_user_id(value: str) -> None:
    _current_user_id.set(value)
