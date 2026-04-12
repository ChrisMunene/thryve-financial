"""
Idempotency primitives for mutation endpoints.

Opt in with `Depends(require_idempotency)` and let `IdempotencyMiddleware`
persist cacheable completed responses.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.config import get_settings
from app.core.exceptions import (
    IdempotencyInProgressError,
    IdempotencyPayloadMismatchError,
)
from app.db.redis import redis_client

logger = structlog.get_logger()

IDEMPOTENCY_PREFIX = "idempotency:"
LOCK_PREFIX = "idempotency_lock:"
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    fingerprint: str
    status_code: int
    body: Any
    is_json: bool
    media_type: str | None
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class IdempotencyContext:
    key: str
    fingerprint: str
    ttl: int
    lock_key: str
    cache_key: str


class IdempotencyReplayResponse(Exception):  # noqa: N818
    """Internal signal used to short-circuit an endpoint with a replayed response."""

    def __init__(self, record: IdempotencyRecord) -> None:
        self.record = record
        super().__init__("Idempotent response replay")

    @classmethod
    def from_json(cls, payload: str) -> IdempotencyReplayResponse:
        raw = json.loads(payload)
        return cls(
            IdempotencyRecord(
                fingerprint=raw["fingerprint"],
                status_code=raw["status_code"],
                body=raw["body"],
                is_json=raw["is_json"],
                media_type=raw.get("media_type"),
                headers=raw.get("headers", {}),
            )
        )

    def to_response(self) -> Response:
        headers = dict(self.record.headers)
        headers["Idempotent-Replayed"] = "true"

        if self.record.is_json:
            return JSONResponse(
                status_code=self.record.status_code,
                content=self.record.body,
                headers=headers,
                media_type=self.record.media_type or "application/json",
            )

        return Response(
            content=self.record.body or b"",
            status_code=self.record.status_code,
            headers=headers,
            media_type=self.record.media_type,
        )


def _canonical_json_body(body: bytes) -> str:
    parsed = json.loads(body)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


async def _request_fingerprint(request: Request) -> str:
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    if body and (
        content_type.split(";", 1)[0].strip().lower() == "application/json"
        or content_type.lower().endswith("+json")
    ):
        try:
            canonical_body = _canonical_json_body(body)
        except json.JSONDecodeError:
            canonical_body = body.decode("utf-8", errors="replace")
    else:
        canonical_body = body.decode("utf-8", errors="replace")

    route = request.scope.get("route")
    route_template = getattr(route, "path", request.url.path)
    principal = getattr(request.state, "user_id", None) or "anonymous"
    payload = "\n".join(
        [principal, request.method.upper(), route_template, canonical_body]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_record(raw: str) -> IdempotencyRecord:
    payload = json.loads(raw)
    return IdempotencyRecord(
        fingerprint=payload["fingerprint"],
        status_code=payload["status_code"],
        body=payload["body"],
        is_json=payload["is_json"],
        media_type=payload.get("media_type"),
        headers=payload.get("headers", {}),
    )


def _record_to_json(record: IdempotencyRecord) -> str:
    return json.dumps(
        {
            "fingerprint": record.fingerprint,
            "status_code": record.status_code,
            "body": record.body,
            "is_json": record.is_json,
            "media_type": record.media_type,
            "headers": record.headers,
        }
    )


def _cacheable_status(status_code: int) -> bool:
    return (200 <= status_code < 300) or status_code == 409


async def require_idempotency(request: Request) -> None:
    """Enable idempotency for a mutation endpoint when a key is supplied."""

    if request.method.upper() not in _MUTATION_METHODS:
        return

    key = request.headers.get("idempotency-key")
    if not key:
        return

    settings = get_settings()
    fingerprint = await _request_fingerprint(request)
    redis = redis_client.redis
    cache_key = f"{IDEMPOTENCY_PREFIX}{key}"
    lock_key = f"{LOCK_PREFIX}{key}"

    cached = await redis.get(cache_key)
    if cached:
        record = _parse_record(cached)
        if record.fingerprint != fingerprint:
            raise IdempotencyPayloadMismatchError.default()
        logger.info("idempotency.cache_hit", idempotency_key=key)
        raise IdempotencyReplayResponse(record)

    acquired = await redis.set(lock_key, fingerprint, nx=True, ex=30)
    if not acquired:
        locked_fingerprint = await redis.get(lock_key)
        if locked_fingerprint and locked_fingerprint != fingerprint:
            raise IdempotencyPayloadMismatchError.default()

        for _ in range(3):
            await asyncio.sleep(0.3)
            cached = await redis.get(cache_key)
            if not cached:
                continue

            record = _parse_record(cached)
            if record.fingerprint != fingerprint:
                raise IdempotencyPayloadMismatchError.default()
            logger.info("idempotency.cache_hit", idempotency_key=key)
            raise IdempotencyReplayResponse(record)

        raise IdempotencyInProgressError.default()

    request.state.idempotency_context = IdempotencyContext(
        key=key,
        fingerprint=fingerprint,
        ttl=settings.idempotency_ttl,
        lock_key=lock_key,
        cache_key=cache_key,
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Persist completed idempotent responses after the endpoint returns."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            response = await call_next(request)
        except Exception:
            context = getattr(request.state, "idempotency_context", None)
            if context is not None:
                await redis_client.redis.delete(context.lock_key)
            raise

        context = getattr(request.state, "idempotency_context", None)
        if context is None or not _cacheable_status(response.status_code):
            if context is not None:
                await redis_client.redis.delete(context.lock_key)
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk.encode("utf-8") if isinstance(chunk, str) else chunk

        response.body_iterator = iterate_in_threadpool(iter([body]))
        await _store_response(
            context,
            response.status_code,
            [
                (key.encode("latin1"), value.encode("latin1"))
                for key, value in response.headers.items()
            ],
            [body],
        )
        await redis_client.redis.delete(context.lock_key)
        return response


async def _store_response(
    context: IdempotencyContext,
    status_code: int,
    response_headers: list[tuple[bytes, bytes]],
    response_chunks: list[bytes],
) -> None:
    body = b"".join(response_chunks)
    header_map = {
        key.decode("latin1"): value.decode("latin1")
        for key, value in response_headers
    }
    media_type = header_map.get("content-type")
    filtered_headers = {
        key: value
        for key, value in header_map.items()
        if key.lower() not in {"content-length", "x-request-id"}
    }

    is_json = False
    body_value: Any
    if body:
        try:
            body_value = json.loads(body)
            is_json = True
        except json.JSONDecodeError:
            body_value = body.decode("utf-8", errors="replace")
    else:
        body_value = None

    record = IdempotencyRecord(
        fingerprint=context.fingerprint,
        status_code=status_code,
        body=body_value,
        is_json=is_json,
        media_type=media_type,
        headers=filtered_headers,
    )
    await redis_client.redis.set(
        context.cache_key,
        _record_to_json(record),
        ex=context.ttl,
    )
    logger.info("idempotency.stored", idempotency_key=context.key)
