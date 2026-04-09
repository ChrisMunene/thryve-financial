"""
Cursor-based pagination — reusable FastAPI dependency.

Parses cursor + limit from query params. Provides encode/decode helpers.
Wired into the PaginatedResponse envelope.
"""

import base64
from dataclasses import dataclass

from fastapi import Query


@dataclass
class PaginationParams:
    cursor: str | None = None
    limit: int = 20


def get_pagination(
    cursor: str | None = Query(None, description="Opaque cursor for next page"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
) -> PaginationParams:
    """FastAPI dependency for pagination parameters."""
    return PaginationParams(cursor=cursor, limit=min(limit, 100))


def encode_cursor(value: str) -> str:
    """Encode a cursor value (typically created_at + id) to opaque string."""
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Decode an opaque cursor back to the original value."""
    return base64.urlsafe_b64decode(cursor.encode()).decode()
