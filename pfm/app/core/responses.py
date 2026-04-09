"""
Standardized response envelope.

All API responses follow these shapes:
- Success: {"data": ...}
- Error: {"error": {"code": "...", "message": "...", "request_id": "..."}}
- Paginated: {"data": [...], "pagination": {"cursor": "...", "has_more": true}}
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    cursor: str | None = None
    has_more: bool = False
    total: int | None = None


class Response(BaseModel, Generic[T]):
    """Standard success response envelope."""

    data: T


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response envelope."""

    data: list[T]
    pagination: PaginationMeta


class ErrorDetail(BaseModel):
    """Error information in the envelope."""

    code: str
    message: str
    details: list[str] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorDetail


def success_response(data: Any) -> Response:
    """Wrap data in the success envelope."""
    return Response(data=data)


def paginated_response(
    data: list[Any],
    cursor: str | None = None,
    has_more: bool = False,
    total: int | None = None,
) -> PaginatedResponse:
    """Wrap list data in the paginated envelope."""
    return PaginatedResponse(
        data=data,
        pagination=PaginationMeta(cursor=cursor, has_more=has_more, total=total),
    )


def error_response(
    code: str,
    message: str,
    details: list[str] | None = None,
    request_id: str | None = None,
) -> ErrorResponse:
    """Build the error envelope."""
    return ErrorResponse(
        error=ErrorDetail(
            code=code, message=message, details=details, request_id=request_id,
        ),
    )
