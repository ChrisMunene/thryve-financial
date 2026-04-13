"""
Response models for API success and problem responses.

Success envelopes intentionally stay unchanged.
Errors use RFC 9457 problem details with a few first-party extensions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.user_actions import UserAction

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"


class PaginationMeta(BaseModel):
    cursor: str | None = None
    has_more: bool = False
    total: int | None = None


class Response[T](BaseModel):
    """Standard success response envelope."""

    ok: Literal[True] = True
    data: T


class PaginatedResponse[T](Response[list[T]]):
    """Paginated list response envelope."""

    pagination: PaginationMeta


class ProblemFieldError(BaseModel):
    """A machine-readable field-level validation issue."""

    source: Literal["body", "query", "path", "header", "cookie", "unknown"]
    field: str | None = None
    code: str
    message: str


class ProblemUpstream(BaseModel):
    """Safe upstream-provider metadata surfaced to first-party clients."""

    provider: str
    provider_code: str | None = None
    provider_request_id: str | None = None


class ProblemResponse(BaseModel):
    """RFC 9457 problem details response plus first-party extensions."""

    model_config = ConfigDict(populate_by_name=True)

    ok: Literal[False] = False
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str | None = None
    retryable: bool = False
    errors: list[ProblemFieldError] | None = None
    upstream: ProblemUpstream | None = None
    user_action: UserAction | None = None


def success_response[T](data: T) -> Response[T]:
    """Wrap data in the success envelope."""
    return Response(data=data)


def paginated_response[T](
    data: list[T],
    cursor: str | None = None,
    has_more: bool = False,
    total: int | None = None,
) -> PaginatedResponse[T]:
    """Wrap list data in the paginated envelope."""
    return PaginatedResponse(
        data=data,
        pagination=PaginationMeta(cursor=cursor, has_more=has_more, total=total),
    )
