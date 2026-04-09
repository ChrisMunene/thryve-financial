"""
Rate limiting — Redis sliding window counter.

Per-user limits (by user_id or IP). Per-endpoint limits via dependency.
Returns 429 with Retry-After and X-RateLimit-* headers on exceed.
"""

import hashlib
import time
from typing import Any

import structlog
from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.exceptions import RateLimitError
from app.core.responses import error_response
from app.db.redis import redis_client

logger = structlog.get_logger()
_UNLIMITED_PATHS = {
    "/health",
    "/health/ready",
    "/api/v1/health",
    "/api/v1/health/ready",
}


def _is_unlimited_path(path: str) -> bool:
    return path in _UNLIMITED_PATHS


def _resolve_request_identity(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"token:{token_hash}"

    return request.client.host if request.client else "unknown"


async def _check_rate_limit(key: str, limit: int, window: int) -> dict[str, int]:
    """Sliding window rate limit check.

    Returns limit metadata for the current request.
    Raises RateLimitError if exceeded.
    """
    if limit <= 0:
        raise ValueError("Rate limit 'limit' must be greater than 0")
    if window <= 0:
        raise ValueError("Rate limit 'window' must be greater than 0")

    redis = redis_client.redis
    now = time.time()
    window_start = now - window + 1

    async with redis.pipeline() as pipe:
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Count requests in window
        pipe.zcard(key)
        # Set TTL on the key
        pipe.expire(key, window)

        results = await pipe.execute()
    request_count = results[2]

    remaining = max(0, limit - request_count)
    reset_at = int(now + window)
    retry_after = max(1, int(reset_at - now))
    metadata = {
        "remaining": remaining,
        "limit": limit,
        "reset_at": reset_at,
        "retry_after": retry_after,
    }

    if request_count >= limit:
        raise RateLimitError(
            message=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            details=[str(reset_at), str(retry_after)],
        )

    return metadata


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global per-user rate limiting middleware."""

    def __init__(self, app: Any, default_limit: int = 100, window: int = 60) -> None:
        super().__init__(app)
        self._default_limit = default_limit
        self._window = window

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_unlimited_path(request.url.path):
            return await call_next(request)

        identity = _resolve_request_identity(request)
        key = f"ratelimit:global:{identity}"

        try:
            metadata = await _check_rate_limit(
                key, self._default_limit, self._window
            )
        except RateLimitError as e:
            reset_at = int(e.details[0]) if e.details else int(time.time()) + self._window
            retry_after = int(e.details[1]) if e.details else self._window

            return JSONResponse(
                status_code=429,
                content=error_response(
                    code="RATE_LIMIT_EXCEEDED",
                    message=e.message,
                ).model_dump(),
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self._default_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                },
            )
        except Exception as exc:
            logger.warning("rate_limit.unavailable", error=str(exc), key=key)
            return await call_next(request)

        response = await call_next(request)

        # Add rate limit headers to every response
        response.headers["X-RateLimit-Limit"] = str(self._default_limit)
        response.headers["X-RateLimit-Remaining"] = str(metadata["remaining"])
        response.headers["X-RateLimit-Reset"] = str(metadata["reset_at"])

        return response


def rate_limit(limit: int = 10, window: int = 60):
    """Per-endpoint rate limit dependency.

    Usage:
        @router.post("/expensive", dependencies=[Depends(rate_limit(limit=10, window=60))])
    """

    async def _check(request: Request) -> None:
        identity = _resolve_request_identity(request)
        key = f"ratelimit:endpoint:{request.url.path}:{identity}"
        try:
            metadata = await _check_rate_limit(key, limit, window)
        except Exception as exc:
            logger.warning("rate_limit.endpoint_unavailable", error=str(exc), key=key)
            return

        request.state.rate_limit_metadata = metadata

    return _check
