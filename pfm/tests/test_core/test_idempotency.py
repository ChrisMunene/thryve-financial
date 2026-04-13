"""End-to-end tests for the production idempotency executor."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, Integer, String, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.delegate import TokenPayload
from app.auth.mock import MockAuthDelegate
from app.config import get_settings
from app.core.analytics import AnalyticsService, ConsoleAnalyticsDelegate
from app.core.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_STATUS_HEADER,
    IdempotencyExecutor,
    IdempotencyPolicy,
    IdempotencyResultRef,
    IdempotentOperationResult,
    get_idempotency_executor,
    register_idempotency_serializer,
    reset_idempotency_serializers,
)
from app.db.redis import redis_client
from app.dependencies import _get_auth_delegate, get_current_user
from app.main import create_app
from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.idempotency import IdempotencyRequest


class ProbeMutation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "probe_mutations"

    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counter: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProbeSerializer:
    async def build_response(
        self,
        *,
        request: Request,
        session: AsyncSession,
        result_ref: IdempotencyResultRef,
        response_status_code: int,
        result_type: str | None,
    ) -> JSONResponse:
        mutation_id = uuid.UUID(result_ref.reference["mutation_id"])
        mutation = await session.get(ProbeMutation, mutation_id)
        if mutation is None:
            raise RuntimeError("Probe mutation was not found for idempotent replay.")

        return JSONResponse(
            status_code=response_status_code,
            content={
                "mutation_id": str(mutation.id),
                "actor": mutation.actor,
                "item_id": mutation.item_id,
                "variant": mutation.variant,
                "counter": mutation.counter,
                "payload": mutation.payload,
            },
        )


class TokenScopedAuthDelegate:
    def __init__(self) -> None:
        self._users = {
            "alice-token": str(uuid.uuid4()),
            "bob-token": str(uuid.uuid4()),
        }

    async def verify_token(self, token: str) -> TokenPayload:
        return TokenPayload(
            user_id=self._users[token],
            email=f"{token}@example.com",
            roles=["user"],
        )


class CacheWriteFailRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if key.startswith("idempotency:v2:"):
            raise RuntimeError("cache write failed")
        self._data[key] = value
        return True

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class ExplodingRedis:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def get(self, key: str) -> str | None:
        raise RuntimeError("cache unavailable")

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        raise RuntimeError("cache unavailable")

    async def delete(self, key: str) -> None:
        raise RuntimeError("cache unavailable")


@pytest.fixture
async def idempotency_session_factory():
    schema_name = f"test_idempotency_{uuid.uuid4().hex}"
    base_url = get_settings().database.url
    admin_engine = create_async_engine(base_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = create_async_engine(
        base_url,
        connect_args={"server_settings": {"search_path": schema_name}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await admin_engine.dispose()


@pytest.fixture
async def idempotency_app(fake_redis, idempotency_session_factory):
    application = create_app()
    mock_delegate = MockAuthDelegate()
    application.state.shutting_down = False
    application.state.analytics = AnalyticsService(delegates=[ConsoleAnalyticsDelegate()])
    application.dependency_overrides[_get_auth_delegate] = lambda: mock_delegate
    application.dependency_overrides[get_idempotency_executor] = lambda: IdempotencyExecutor(
        session_factory=idempotency_session_factory,
        policy=IdempotencyPolicy(
            retention_seconds=300,
            processing_lease_seconds=5,
            cache_ttl_seconds=60,
        ),
    )
    register_idempotency_serializer("probe", ProbeSerializer())
    try:
        yield application
    finally:
        reset_idempotency_serializers()


@pytest.fixture
async def idempotency_client(idempotency_app):
    transport = ASGITransport(app=idempotency_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _install_probe_route(
    app,
    *,
    call_count: dict[str, int],
    require_auth: bool = True,
    started: asyncio.Event | None = None,
    sleep_seconds: float = 0.0,
):
    if require_auth:

        @app.post("/probe-idempotent/{item_id}")
        async def probe_idempotent(
            item_id: str,
            request: Request,
            payload: dict = Body(...),
            variant: str | None = Query(default=None),
            executor: IdempotencyExecutor = Depends(get_idempotency_executor),
            current_user=Depends(get_current_user),
        ):
            actor = str(current_user.user_id)

            async def operation(session: AsyncSession) -> IdempotentOperationResult:
                if started is not None:
                    started.set()
                if sleep_seconds:
                    await asyncio.sleep(sleep_seconds)
                call_count["value"] += 1
                mutation = ProbeMutation(
                    actor=actor,
                    item_id=item_id,
                    variant=variant,
                    counter=call_count["value"],
                    payload=payload,
                )
                session.add(mutation)
                await session.flush()
                response = JSONResponse(
                    status_code=201,
                    content={
                        "mutation_id": str(mutation.id),
                        "actor": actor,
                        "item_id": item_id,
                        "variant": variant,
                        "counter": call_count["value"],
                        "payload": payload,
                    },
                )
                return IdempotentOperationResult(
                    response=response,
                    result_ref=IdempotencyResultRef(
                        serializer="probe",
                        reference={"mutation_id": str(mutation.id)},
                    ),
                )

            return await executor.execute(
                request=request,
                operation=operation,
                operation_name="probe.write",
            )

        return probe_idempotent

    @app.post("/probe-anonymous/{item_id}")
    async def probe_anonymous(
        item_id: str,
        request: Request,
        payload: dict = Body(...),
        executor: IdempotencyExecutor = Depends(get_idempotency_executor),
    ):
        actor = getattr(request.state, "anonymous_id", "missing")

        async def operation(session: AsyncSession) -> IdempotentOperationResult:
            call_count["value"] += 1
            mutation = ProbeMutation(
                actor=actor,
                item_id=item_id,
                variant=None,
                counter=call_count["value"],
                payload=payload,
            )
            session.add(mutation)
            await session.flush()
            response = JSONResponse(
                status_code=201,
                content={
                    "mutation_id": str(mutation.id),
                    "actor": actor,
                    "item_id": item_id,
                    "variant": None,
                    "counter": call_count["value"],
                    "payload": payload,
                },
            )
            return IdempotentOperationResult(
                response=response,
                result_ref=IdempotencyResultRef(
                    serializer="probe",
                    reference={"mutation_id": str(mutation.id)},
                ),
            )

        return await executor.execute(
            request=request,
            operation=operation,
            operation_name="probe.anonymous",
        )

    return probe_anonymous


async def test_missing_idempotency_key_returns_428(idempotency_app, idempotency_client):
    _install_probe_route(idempotency_app, call_count={"value": 0})

    response = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers={"authorization": "Bearer token-123"},
    )

    assert response.status_code == 428
    assert response.json()["code"] == "idempotency_key_required"


async def test_anonymous_mutation_requires_valid_anonymous_id(idempotency_app, idempotency_client):
    _install_probe_route(idempotency_app, call_count={"value": 0}, require_auth=False)

    response = await idempotency_client.post(
        "/probe-anonymous/widget-1",
        json={"amount": 10},
        headers={IDEMPOTENCY_KEY_HEADER: "anon-key"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_scope_required"


async def test_replays_completed_response_with_reference_serializer(
    idempotency_app,
    idempotency_client,
):
    call_count = {"value": 0}
    _install_probe_route(idempotency_app, call_count=call_count)

    headers = {
        "authorization": "Bearer token-123",
        IDEMPOTENCY_KEY_HEADER: "replay-key",
    }
    first = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10, "currency": "USD"},
        headers=headers,
    )
    second = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"currency": "USD", "amount": 10},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert call_count["value"] == 1
    assert first.headers[IDEMPOTENCY_STATUS_HEADER] == "created"
    assert second.headers[IDEMPOTENCY_STATUS_HEADER] == "replayed"
    assert second.headers[IDEMPOTENCY_KEY_HEADER] == "replay-key"


async def test_path_and_query_params_participate_in_fingerprint(
    idempotency_app,
    idempotency_client,
):
    call_count = {"value": 0}
    _install_probe_route(idempotency_app, call_count=call_count)
    headers = {
        "authorization": "Bearer token-123",
        IDEMPOTENCY_KEY_HEADER: "mismatch-key",
    }

    first = await idempotency_client.post(
        "/probe-idempotent/widget-1?variant=primary",
        json={"amount": 10},
        headers=headers,
    )
    second = await idempotency_client.post(
        "/probe-idempotent/widget-2?variant=primary",
        json={"amount": 10},
        headers=headers,
    )
    third = await idempotency_client.post(
        "/probe-idempotent/widget-1?variant=secondary",
        json={"amount": 10},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert third.status_code == 409
    assert second.json()["code"] == "idempotency_payload_mismatch"
    assert third.json()["code"] == "idempotency_payload_mismatch"
    assert call_count["value"] == 1


async def test_different_users_do_not_collide_on_same_idempotency_key(
    idempotency_app,
    idempotency_client,
):
    call_count = {"value": 0}
    _install_probe_route(idempotency_app, call_count=call_count)
    token_delegate = TokenScopedAuthDelegate()
    idempotency_app.dependency_overrides[_get_auth_delegate] = lambda: token_delegate

    alice_headers = {
        "authorization": "Bearer alice-token",
        IDEMPOTENCY_KEY_HEADER: "shared-key",
    }
    bob_headers = {
        "authorization": "Bearer bob-token",
        IDEMPOTENCY_KEY_HEADER: "shared-key",
    }

    alice = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=alice_headers,
    )
    bob = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=bob_headers,
    )
    alice_replay = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=alice_headers,
    )

    assert alice.status_code == 201
    assert bob.status_code == 201
    assert alice.json()["actor"] != bob.json()["actor"]
    assert alice_replay.status_code == 201
    assert alice_replay.json() == alice.json()
    assert alice_replay.headers[IDEMPOTENCY_STATUS_HEADER] == "replayed"
    assert call_count["value"] == 2


async def test_in_progress_request_returns_409_without_double_execution(
    idempotency_app,
    idempotency_client,
):
    call_count = {"value": 0}
    started = asyncio.Event()
    _install_probe_route(
        idempotency_app,
        call_count=call_count,
        started=started,
        sleep_seconds=1.2,
    )

    headers = {
        "authorization": "Bearer token-123",
        IDEMPOTENCY_KEY_HEADER: "in-progress-key",
    }
    first_request = asyncio.create_task(
        idempotency_client.post(
            "/probe-idempotent/widget-1",
            json={"amount": 10},
            headers=headers,
        )
    )
    await started.wait()

    second = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=headers,
    )
    first = await first_request

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_request_in_progress"
    assert second.headers["retry-after"] in {"4", "5"}
    assert second.headers[IDEMPOTENCY_STATUS_HEADER] == "in_progress"
    assert call_count["value"] == 1


async def test_expired_lease_is_reclaimed_and_then_replayed(
    idempotency_app,
    idempotency_client,
    idempotency_session_factory,
):
    call_count = {"value": 0}
    _install_probe_route(idempotency_app, call_count=call_count)
    headers = {
        "authorization": "Bearer token-123",
        IDEMPOTENCY_KEY_HEADER: "stale-key",
    }

    first = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=headers,
    )
    assert first.status_code == 201

    async with idempotency_session_factory() as session:
        async with session.begin():
            record = await session.scalar(
                select(IdempotencyRequest).where(
                    IdempotencyRequest.idempotency_key == "stale-key"
                )
            )
            assert record is not None
            record.status = "processing"
            record.lease_owner = "stale-owner"
            record.lease_expires_at = record.updated_at - timedelta(seconds=10)
            record.result_type = None
            record.result_ref = None
            record.response_status_code = None

    second = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=headers,
    )
    third = await idempotency_client.post(
        "/probe-idempotent/widget-1",
        json={"amount": 10},
        headers=headers,
    )

    assert second.status_code == 201
    assert second.headers[IDEMPOTENCY_STATUS_HEADER] == "created"
    assert third.status_code == 201
    assert third.headers[IDEMPOTENCY_STATUS_HEADER] == "replayed"
    assert third.json() == second.json()
    assert call_count["value"] == 2


async def test_success_survives_cache_write_failure_and_replays_from_database(
    idempotency_app,
    idempotency_client,
):
    call_count = {"value": 0}
    _install_probe_route(idempotency_app, call_count=call_count)
    original_redis = redis_client._redis
    redis_client._redis = CacheWriteFailRedis()
    try:
        headers = {
            "authorization": "Bearer token-123",
            IDEMPOTENCY_KEY_HEADER: "cache-failure-key",
        }
        first = await idempotency_client.post(
            "/probe-idempotent/widget-1",
            json={"amount": 10},
            headers=headers,
        )
        second = await idempotency_client.post(
            "/probe-idempotent/widget-1",
            json={"amount": 10},
            headers=headers,
        )
    finally:
        redis_client._redis = original_redis

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers[IDEMPOTENCY_STATUS_HEADER] == "replayed"
    assert second.json() == first.json()
    assert call_count["value"] == 1


async def test_redis_outage_falls_back_to_database(idempotency_app, idempotency_client):
    call_count = {"value": 0}
    _install_probe_route(idempotency_app, call_count=call_count)
    original_redis = redis_client._redis
    redis_client._redis = ExplodingRedis()
    try:
        headers = {
            "authorization": "Bearer token-123",
            IDEMPOTENCY_KEY_HEADER: "redis-outage-key",
        }
        first = await idempotency_client.post(
            "/probe-idempotent/widget-1",
            json={"amount": 10},
            headers=headers,
        )
        second = await idempotency_client.post(
            "/probe-idempotent/widget-1",
            json={"amount": 10},
            headers=headers,
        )
    finally:
        redis_client._redis = original_redis

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers[IDEMPOTENCY_STATUS_HEADER] == "replayed"
    assert call_count["value"] == 1
