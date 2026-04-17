"""Production idempotency primitives for mutation endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

import structlog
from fastapi import Request
from fastapi.responses import Response
from fastapi.routing import APIRoute
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyRequiredError,
    IdempotencyPayloadMismatchError,
    IdempotencyScopeRequiredError,
)
from app.core.telemetry import get_metrics
from app.db.session import get_async_session_factory
from app.models.idempotency import IdempotencyRequest

logger = structlog.get_logger()

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_STATUS_HEADER = "Idempotency-Status"
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_IDEMPOTENCY_ATTR = "__skip_idempotency__"


class IdempotencyRecordStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class IdempotencyResponseStatus(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"
    IN_PROGRESS = "in_progress"


class IdempotencyScopeKind(StrEnum):
    USER = "user"
    ANONYMOUS = "anon"


class IdempotencyStorageSource(StrEnum):
    DATABASE = "db"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class IdempotencyScope:
    kind: IdempotencyScopeKind
    subject: str

    @property
    def value(self) -> str:
        return f"{self.kind.value}:{self.subject}"


@dataclass(frozen=True, slots=True)
class IdempotencyPolicy:
    retention_seconds: int
    processing_lease_seconds: int
    fingerprint_version: int = 1

    @classmethod
    def from_settings(cls, settings: Settings) -> IdempotencyPolicy:
        return cls(
            retention_seconds=settings.idempotency_retention_seconds,
            processing_lease_seconds=settings.idempotency_processing_lease_seconds,
        )


@dataclass(frozen=True, slots=True)
class IdempotencyResultRef:
    serializer: str
    version: int = 1
    reference: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "serializer": self.serializer,
            "version": self.version,
            "reference": self.reference,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> IdempotencyResultRef:
        return cls(
            serializer=str(payload["serializer"]),
            version=int(payload.get("version", 1)),
            reference=dict(payload.get("reference", {})),
        )


class IdempotencyReplaySerializer(Protocol):
    async def build_response(
        self,
        *,
        request: Request,
        session: AsyncSession,
        result_ref: IdempotencyResultRef,
        response_status_code: int,
        result_type: str | None,
    ) -> Response: ...


class IdempotencySerializerRegistry:
    def __init__(self) -> None:
        self._serializers: dict[str, IdempotencyReplaySerializer] = {}

    def register(
        self,
        serializer_name: str,
        serializer: IdempotencyReplaySerializer,
    ) -> None:
        self._serializers[serializer_name] = serializer

    def unregister(self, serializer_name: str) -> None:
        self._serializers.pop(serializer_name, None)

    def clear(self) -> None:
        self._serializers.clear()

    def serializer_for(self, serializer_name: str) -> IdempotencyReplaySerializer:
        serializer = self._serializers.get(serializer_name)
        if serializer is None:
            raise LookupError(f"No idempotency serializer registered for {serializer_name!r}")
        return serializer


_serializer_registry = IdempotencySerializerRegistry()


def register_idempotency_serializer(
    serializer_name: str,
    serializer: IdempotencyReplaySerializer,
) -> None:
    _serializer_registry.register(serializer_name, serializer)


def unregister_idempotency_serializer(serializer_name: str) -> None:
    _serializer_registry.unregister(serializer_name)


def reset_idempotency_serializers() -> None:
    _serializer_registry.clear()


def skip_idempotency(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Opt a mutation route out of automatic key enforcement."""

    setattr(endpoint, _SKIP_IDEMPOTENCY_ATTR, True)
    return endpoint


@dataclass(frozen=True, slots=True)
class IdempotentOperationResult:
    response: Response
    result_ref: IdempotencyResultRef
    persist: bool | None = None
    result_type: str | None = None
    error_code: str | None = None

    def should_persist(self) -> bool:
        if self.persist is not None:
            return self.persist
        return 200 <= self.response.status_code < 300


@dataclass(frozen=True, slots=True)
class _ResolvedIdempotencyRequest:
    key: str
    key_hash: str
    scope: IdempotencyScope
    endpoint: str
    fingerprint_hash: str
    fingerprint_version: int


@dataclass(frozen=True, slots=True)
class _ClaimedRequest:
    record_id: uuid.UUID
    lease_owner: str
    lease_stolen: bool


@dataclass(frozen=True, slots=True)
class _ReplayTarget:
    record_id: uuid.UUID
    storage_source: IdempotencyStorageSource


@dataclass(frozen=True, slots=True)
class _InProgressTarget:
    retry_after_seconds: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _truncate_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _json_content_type(content_type: str) -> bool:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized == "application/json" or normalized.endswith("+json")


def _canonical_json_text(body: bytes) -> str:
    parsed = json.loads(body)
    return json.dumps(
        parsed,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _normalize_path_params(request: Request) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in sorted(request.path_params.items(), key=lambda item: item[0])
    }


def _normalize_query_params(request: Request) -> list[tuple[str, str]]:
    return sorted(
        [(key, value) for key, value in request.query_params.multi_items()],
        key=lambda item: (item[0], item[1]),
    )


async def _body_digest(request: Request) -> str:
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    if body and _json_content_type(content_type):
        try:
            normalized = _canonical_json_text(body).encode("utf-8")
        except (json.JSONDecodeError, ValueError):
            normalized = body
    else:
        normalized = body
    return hashlib.sha256(normalized).hexdigest()


async def _resolve_idempotency_request(
    request: Request,
    *,
    policy: IdempotencyPolicy,
    operation_name: str | None,
) -> _ResolvedIdempotencyRequest:
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not key:
        raise IdempotencyKeyRequiredError.default()

    user_id = getattr(request.state, "user_id", None)
    if user_id:
        scope = IdempotencyScope(IdempotencyScopeKind.USER, str(user_id))
    else:
        anonymous_id = getattr(request.state, "anonymous_id", None)
        if not anonymous_id:
            raise IdempotencyScopeRequiredError.default()
        scope = IdempotencyScope(IdempotencyScopeKind.ANONYMOUS, str(anonymous_id))

    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    route_name = getattr(route, "name", None) or "endpoint"
    endpoint = operation_name or f"{request.method.upper()}:{route_path}:{route_name}"
    content_type = request.headers.get("content-type", "")
    fingerprint_payload = {
        "scope": scope.value,
        "method": request.method.upper(),
        "endpoint": endpoint,
        "path_params": _normalize_path_params(request),
        "query_params": _normalize_query_params(request),
        "content_type": content_type.split(";", 1)[0].strip().lower(),
        "body_digest": await _body_digest(request),
    }
    fingerprint_hash = hashlib.sha256(
        json.dumps(fingerprint_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return _ResolvedIdempotencyRequest(
        key=key,
        key_hash=_truncate_hash(key),
        scope=scope,
        endpoint=endpoint,
        fingerprint_hash=fingerprint_hash,
        fingerprint_version=policy.fingerprint_version,
    )


def _annotate_span(**attributes: str) -> None:
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in attributes.items():
        span.set_attribute(key, value)


class IdempotencyRoute(APIRoute):
    """Require Idempotency-Key on public mutation endpoints by default."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original_handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            if (
                request.method.upper() in _MUTATION_METHODS
                and not getattr(self.endpoint, _SKIP_IDEMPOTENCY_ATTR, False)
                and not request.headers.get(IDEMPOTENCY_KEY_HEADER)
            ):
                get_metrics().record_idempotency_request(
                    status="missing_key",
                    storage_source=IdempotencyStorageSource.NONE.value,
                )
                raise IdempotencyKeyRequiredError.default()
            return await original_handler(request)

        return route_handler


class IdempotencyExecutor:
    """Execute a mutation once and replay completed results safely."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        policy: IdempotencyPolicy,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy

    async def execute(
        self,
        *,
        request: Request,
        operation: Callable[[AsyncSession], Awaitable[IdempotentOperationResult]],
        operation_name: str | None = None,
        policy: IdempotencyPolicy | None = None,
    ) -> Response:
        effective_policy = policy or self._policy
        resolved = await _resolve_idempotency_request(
            request,
            policy=effective_policy,
            operation_name=operation_name,
        )

        _annotate_span(
            **{
                "idempotency.scope": resolved.scope.value,
                "idempotency.key_hash": resolved.key_hash,
                "idempotency.endpoint": resolved.endpoint,
            }
        )

        while True:
            claim = await self._claim_request(resolved, effective_policy)
            if isinstance(claim, _ReplayTarget):
                replay = await self._replay_record(
                    request=request,
                    resolved=resolved,
                    record_id=claim.record_id,
                    storage_source=claim.storage_source,
                )
                if replay is not None:
                    return replay
                continue

            if isinstance(claim, _InProgressTarget):
                get_metrics().record_idempotency_request(
                    status=IdempotencyResponseStatus.IN_PROGRESS.value,
                    storage_source=IdempotencyStorageSource.DATABASE.value,
                )
                raise IdempotencyInProgressError.for_retry_after(claim.retry_after_seconds)

            return await self._execute_claimed_operation(
                request=request,
                resolved=resolved,
                claim=claim,
                effective_policy=effective_policy,
                operation=operation,
            )

    async def _claim_request(
        self,
        resolved: _ResolvedIdempotencyRequest,
        policy: IdempotencyPolicy,
    ) -> _ClaimedRequest | _ReplayTarget | _InProgressTarget:
        lease_owner = uuid.uuid4().hex
        lease_expires_at = _utcnow() + timedelta(seconds=policy.processing_lease_seconds)

        while True:
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        record = await session.scalar(
                            select(IdempotencyRequest).where(
                                IdempotencyRequest.scope == resolved.scope.value,
                                IdempotencyRequest.idempotency_key == resolved.key,
                            )
                        )
                        now = _utcnow()
                        if record is None:
                            record = IdempotencyRequest(
                                scope=resolved.scope.value,
                                idempotency_key=resolved.key,
                                endpoint=resolved.endpoint,
                                fingerprint_hash=resolved.fingerprint_hash,
                                fingerprint_version=resolved.fingerprint_version,
                                status=IdempotencyRecordStatus.PROCESSING.value,
                                lease_owner=lease_owner,
                                lease_expires_at=lease_expires_at,
                                expires_at=now + timedelta(seconds=policy.retention_seconds),
                            )
                            session.add(record)
                            await session.flush()
                            return _ClaimedRequest(
                                record_id=record.id,
                                lease_owner=lease_owner,
                                lease_stolen=False,
                            )

                        if record.expires_at <= now:
                            await session.delete(record)
                            continue

                        if (
                            record.fingerprint_hash != resolved.fingerprint_hash
                            or record.fingerprint_version != resolved.fingerprint_version
                        ):
                            get_metrics().record_idempotency_request(
                                status="mismatch",
                                storage_source=IdempotencyStorageSource.DATABASE.value,
                            )
                            raise IdempotencyPayloadMismatchError.default()

                        if record.status == IdempotencyRecordStatus.COMPLETED.value:
                            return _ReplayTarget(
                                record_id=record.id,
                                storage_source=IdempotencyStorageSource.DATABASE,
                            )

                        if (
                            record.lease_expires_at is not None
                            and record.lease_expires_at > now
                        ):
                            retry_after = max(
                                1,
                                int((record.lease_expires_at - now).total_seconds()),
                            )
                            return _InProgressTarget(retry_after_seconds=retry_after)

                        record.status = IdempotencyRecordStatus.PROCESSING.value
                        record.lease_owner = lease_owner
                        record.lease_expires_at = lease_expires_at
                        record.endpoint = resolved.endpoint
                        record.result_type = None
                        record.result_ref = None
                        record.response_status_code = None
                        record.error_code = None
                        record.expires_at = now + timedelta(seconds=policy.retention_seconds)
                        await session.flush()
                        get_metrics().record_idempotency_lease_steal()
                        logger.warning(
                            "idempotency.lease_reclaimed",
                            idempotency_key_hash=resolved.key_hash,
                            scope=resolved.scope.value,
                            endpoint=resolved.endpoint,
                        )
                        return _ClaimedRequest(
                            record_id=record.id,
                            lease_owner=lease_owner,
                            lease_stolen=True,
                        )
            except IntegrityError:
                continue

    async def _execute_claimed_operation(
        self,
        *,
        request: Request,
        resolved: _ResolvedIdempotencyRequest,
        claim: _ClaimedRequest,
        effective_policy: IdempotencyPolicy,
        operation: Callable[[AsyncSession], Awaitable[IdempotentOperationResult]],
    ) -> Response:
        stop_renewal = asyncio.Event()
        renewal_task = asyncio.create_task(
            self._renew_lease(
                record_id=claim.record_id,
                lease_owner=claim.lease_owner,
                stop_signal=stop_renewal,
                policy=effective_policy,
            )
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(IdempotencyRequest, claim.record_id)
                    if record is None or record.lease_owner != claim.lease_owner:
                        raise IdempotencyInProgressError.default()

                    result = await operation(session)
                    response = result.response
                    should_persist = result.should_persist()
                    if should_persist:
                        record.status = IdempotencyRecordStatus.COMPLETED.value
                        record.lease_owner = None
                        record.lease_expires_at = None
                        record.result_type = result.result_type or result.result_ref.serializer
                        record.result_ref = result.result_ref.as_json()
                        record.response_status_code = response.status_code
                        record.error_code = result.error_code
                    else:
                        await session.delete(record)

                response.headers[IDEMPOTENCY_KEY_HEADER] = resolved.key
                if should_persist:
                    response.headers[IDEMPOTENCY_STATUS_HEADER] = (
                        IdempotencyResponseStatus.CREATED.value
                    )
                    get_metrics().record_idempotency_request(
                        status=IdempotencyResponseStatus.CREATED.value,
                        storage_source=IdempotencyStorageSource.DATABASE.value,
                    )
                    _annotate_span(
                        **{
                            "idempotency.status": IdempotencyResponseStatus.CREATED.value,
                            "idempotency.storage_source": (
                                IdempotencyStorageSource.DATABASE.value
                            ),
                        }
                    )
                return response
        except Exception:
            await self._release_claim(claim.record_id, claim.lease_owner)
            raise
        finally:
            stop_renewal.set()
            renewal_task.cancel()
            try:
                await renewal_task
            except asyncio.CancelledError:
                pass

    async def _replay_record(
        self,
        *,
        request: Request,
        resolved: _ResolvedIdempotencyRequest,
        record_id: uuid.UUID,
        storage_source: IdempotencyStorageSource,
    ) -> Response | None:
        async with self._session_factory() as session:
            async with session.begin():
                record = await session.get(IdempotencyRequest, record_id)
                if record is None or record.status != IdempotencyRecordStatus.COMPLETED.value:
                    return None

                now = _utcnow()
                if record.expires_at <= now:
                    await session.delete(record)
                    return None

                if (
                    record.fingerprint_hash != resolved.fingerprint_hash
                    or record.fingerprint_version != resolved.fingerprint_version
                ):
                    raise IdempotencyPayloadMismatchError.default()

                if record.result_ref is None or record.response_status_code is None:
                    raise RuntimeError("Completed idempotency record is missing replay metadata.")

                result_ref = IdempotencyResultRef.from_json(dict(record.result_ref))
                serializer = _serializer_registry.serializer_for(result_ref.serializer)
                response = await serializer.build_response(
                    request=request,
                    session=session,
                    result_ref=result_ref,
                    response_status_code=record.response_status_code,
                    result_type=record.result_type,
                )
                record.replay_count += 1
                record.last_replayed_at = now

        response.headers[IDEMPOTENCY_KEY_HEADER] = resolved.key
        response.headers[IDEMPOTENCY_STATUS_HEADER] = IdempotencyResponseStatus.REPLAYED.value
        get_metrics().record_idempotency_request(
            status=IdempotencyResponseStatus.REPLAYED.value,
            storage_source=storage_source.value,
        )
        _annotate_span(
            **{
                "idempotency.status": IdempotencyResponseStatus.REPLAYED.value,
                "idempotency.storage_source": storage_source.value,
            }
        )
        return response

    async def _release_claim(
        self,
        record_id: uuid.UUID,
        lease_owner: str,
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(IdempotencyRequest, record_id)
                    if record is None:
                        return
                    if record.lease_owner != lease_owner:
                        return
                    if record.status == IdempotencyRecordStatus.PROCESSING.value:
                        await session.delete(record)
        except Exception as exc:
            logger.warning("idempotency.release_failed", error=str(exc))

    async def _renew_lease(
        self,
        *,
        record_id: uuid.UUID,
        lease_owner: str,
        stop_signal: asyncio.Event,
        policy: IdempotencyPolicy,
    ) -> None:
        interval_seconds = max(1, policy.processing_lease_seconds // 3)
        while True:
            try:
                await asyncio.wait_for(stop_signal.wait(), timeout=interval_seconds)
                return
            except TimeoutError:
                pass

            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        record = await session.get(IdempotencyRequest, record_id)
                        if record is None:
                            return
                        if (
                            record.lease_owner != lease_owner
                            or record.status != IdempotencyRecordStatus.PROCESSING.value
                        ):
                            return
                        record.lease_expires_at = _utcnow() + timedelta(
                            seconds=policy.processing_lease_seconds
                        )
            except Exception as exc:
                logger.warning("idempotency.lease_renewal_failed", error=str(exc))


def get_idempotency_executor() -> IdempotencyExecutor:
    settings = get_settings()
    return IdempotencyExecutor(
        session_factory=get_async_session_factory(),
        policy=IdempotencyPolicy.from_settings(settings),
    )


async def cleanup_expired_idempotency_requests(
    *,
    batch_size: int | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    settings = get_settings()
    effective_batch_size = batch_size or settings.idempotency_cleanup_batch_size
    effective_session_factory = session_factory or get_async_session_factory()
    async with effective_session_factory() as session:
        async with session.begin():
            now = _utcnow()
            records = (
                await session.scalars(
                    select(IdempotencyRequest)
                    .where(IdempotencyRequest.expires_at <= now)
                    .order_by(IdempotencyRequest.expires_at.asc())
                    .limit(effective_batch_size)
                )
            ).all()
            for record in records:
                await session.delete(record)

    return len(records)


__all__ = [
    "IDEMPOTENCY_KEY_HEADER",
    "IDEMPOTENCY_STATUS_HEADER",
    "IdempotencyExecutor",
    "IdempotencyPolicy",
    "IdempotencyResultRef",
    "IdempotencyResponseStatus",
    "IdempotencyRoute",
    "IdempotencyScope",
    "IdempotencyScopeKind",
    "IdempotentOperationResult",
    "cleanup_expired_idempotency_requests",
    "get_idempotency_executor",
    "register_idempotency_serializer",
    "reset_idempotency_serializers",
    "skip_idempotency",
    "unregister_idempotency_serializer",
]
