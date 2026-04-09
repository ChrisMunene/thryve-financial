"""
Idempotency layer — Redis-backed.

Opt-in per endpoint via require_idempotency dependency.
Uses Redis lock to handle concurrent duplicates.
"""

import asyncio
import json

import structlog
from fastapi import Request, Response
from starlette.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import IdempotencyConflictError
from app.db.redis import redis_client

logger = structlog.get_logger()

IDEMPOTENCY_PREFIX = "idempotency:"
LOCK_PREFIX = "idempotency_lock:"


async def require_idempotency(request: Request) -> None:
    """FastAPI dependency that enforces idempotency on an endpoint.

    Usage:
        @router.post("/corrections", dependencies=[Depends(require_idempotency)])
    """
    key = request.headers.get("idempotency-key")
    if not key:
        return  # No key = no idempotency enforcement

    settings = get_settings()
    ttl = settings.idempotency_ttl
    redis = redis_client.redis
    cache_key = f"{IDEMPOTENCY_PREFIX}{key}"
    lock_key = f"{LOCK_PREFIX}{key}"

    # Check if we've seen this key before
    cached = await redis.get(cache_key)
    if cached:
        # Return the stored response
        stored = json.loads(cached)
        logger.info("idempotency.cache_hit", idempotency_key=key)

        # Store the cached response on request state for the middleware to return
        request.state.idempotent_response = JSONResponse(
            status_code=stored["status_code"],
            content=stored["body"],
        )
        return

    # Try to acquire lock for this key
    acquired = await redis.set(lock_key, "1", nx=True, ex=30)  # 30s lock timeout
    if not acquired:
        # Another request is processing this key — poll with backoff
        for attempt in range(5):
            await asyncio.sleep(0.3 * (attempt + 1))
            cached = await redis.get(cache_key)
            if cached:
                stored = json.loads(cached)
                request.state.idempotent_response = JSONResponse(
                    status_code=stored["status_code"],
                    content=stored["body"],
                )
                return
        raise IdempotencyConflictError("Request is being processed by another call")

    # Mark that we need to store the response after the endpoint executes
    request.state.idempotency_key = key
    request.state.idempotency_ttl = ttl
    request.state.idempotency_lock_key = lock_key


async def store_idempotent_response(request: Request, response: Response) -> None:
    """Store the response for future idempotent lookups.

    NOTE: Not yet wired as middleware. Must be integrated into the request/response
    cycle before idempotency caching is functional. The require_idempotency dependency
    sets request.state flags; this function should be called post-response to persist
    the result.
    """
    key = getattr(request.state, "idempotency_key", None)
    if not key:
        return

    ttl = getattr(request.state, "idempotency_ttl", 86400)
    lock_key = getattr(request.state, "idempotency_lock_key", None)
    redis = redis_client.redis
    cache_key = f"{IDEMPOTENCY_PREFIX}{key}"

    try:
        # Read response body — collect chunks into list to avoid O(n^2) concatenation
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunks.append(chunk)
        body = b"".join(chunks)

        # Re-create the body iterator so the client still receives the response
        response.body_iterator = iter([body])

        try:
            parsed_body = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed_body = body.decode("utf-8", errors="replace") if body else None

        stored = {
            "status_code": response.status_code,
            "body": parsed_body,
        }
        await redis.set(cache_key, json.dumps(stored), ex=ttl)
        logger.info("idempotency.stored", idempotency_key=key)
    finally:
        # Release the lock
        if lock_key:
            await redis.delete(lock_key)
