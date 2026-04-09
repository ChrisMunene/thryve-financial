"""
Correlation ID middleware configuration.

Backed by ``asgi-correlation-id`` for production-safe ASGI handling.
"""

import re
import uuid

from asgi_correlation_id import CorrelationIdMiddleware

_VALID_REQUEST_ID = re.compile(r"^[a-zA-Z0-9\-]{1,128}$")


def generate_correlation_id() -> str:
    """Return a hyphenated UUID4 string to match existing response shape."""
    return str(uuid.uuid4())


def is_valid_request_id(request_id: str) -> bool:
    """Accept the existing application request ID contract."""
    return bool(_VALID_REQUEST_ID.fullmatch(request_id))
