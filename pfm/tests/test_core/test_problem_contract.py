"""End-to-end contract tests for RFC 9457 problem responses."""

from __future__ import annotations

import httpx
from fastapi import Body, Depends, Query, Security
from httpx import ASGITransport, AsyncClient

from app.auth.mock import MockAuthService
from app.clients.base import BaseClient
from app.core.responses import success_response
from app.core.user_actions import UserAction
from app.dependencies import get_auth_service, require_auth, require_roles


class _TimeoutClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(base_url="https://provider.example", service_name="plaid", max_retries=0)
        self._client = httpx.AsyncClient(
            transport=httpx.MockTransport(self._handler),
            base_url="https://provider.example",
            timeout=0.1,
        )

    def _handler(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout", request=request)


class _ProviderErrorClient(BaseClient):
    def __init__(self) -> None:
        super().__init__(base_url="https://provider.example", service_name="plaid", max_retries=0)
        self._client = httpx.AsyncClient(
            transport=httpx.MockTransport(self._handler),
            base_url="https://provider.example",
            timeout=0.1,
        )

    def _handler(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "error_code": "ITEM_LOGIN_REQUIRED",
                "error_message": "secret upstream message",
                "request_id": "plaid-req-123",
            },
        )


async def test_404_normalizes_to_problem_details(client):
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["ok"] is False
    assert response.json()["code"] == "resource_not_found"


async def test_405_normalizes_to_problem_details(client):
    response = await client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


async def test_malformed_json_returns_400_problem(app, client):
    @app.post("/probe-json")
    async def probe_json(payload: dict = Body(...)):
        return success_response(payload)

    response = await client.post(
        "/probe-json",
        content=b'{"bad": ',
        headers={
            "content-type": "application/json",
            "Idempotency-Key": "problem-json-key",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "malformed_request"


async def test_unsupported_media_type_returns_415_problem(app, client):
    @app.post("/probe-media-type")
    async def probe_media_type(payload: dict = Body(...)):
        return success_response(payload)

    response = await client.post(
        "/probe-media-type",
        content="plain text body",
        headers={
            "content-type": "text/plain",
            "Idempotency-Key": "problem-media-type-key",
        },
    )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"


async def test_query_validation_returns_422_with_field_errors(app, client):
    @app.get("/probe-validate")
    async def probe_validate(limit: int = Query(..., ge=1)):
        return {"limit": limit}

    response = await client.get("/probe-validate", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request_validation_failed"
    assert body["errors"][0]["source"] == "query"
    assert body["errors"][0]["field"] == "limit"


async def test_missing_bearer_token_returns_401_with_challenge(app, client):
    @app.get("/probe-auth")
    async def probe_auth(principal=Security(require_auth)):
        return {"subject_id": principal.subject_id}

    response = await client.get("/probe-auth")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "authentication_required"


async def test_insufficient_role_returns_403_without_challenge(app, client):
    @app.get("/probe-admin", dependencies=[Depends(require_roles("admin"))])
    async def probe_admin():
        return {"ok": True}

    response = await client.get(
        "/probe-admin",
        headers={"authorization": "Bearer token-123"},
    )

    assert response.status_code == 403
    assert "www-authenticate" not in response.headers
    assert response.json()["code"] == "permission_denied"


async def test_unhandled_error_returns_sanitized_problem(app, client):
    @app.get("/probe-boom")
    async def probe_boom():
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/probe-boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "boom" not in body["detail"]
    assert body["request_id"] == response.headers["x-request-id"]


async def test_upstream_timeout_maps_to_504_problem(app, client):
    @app.get("/probe-upstream-timeout")
    async def probe_upstream_timeout():
        timeout_client = _TimeoutClient()
        return await timeout_client.get("/timeout")

    response = await client.get("/probe-upstream-timeout")

    assert response.status_code == 504
    assert response.json()["code"] == "upstream_timeout"
    assert response.json()["retryable"] is True


async def test_provider_translation_keeps_safe_upstream_metadata(app, client):
    @app.get("/probe-provider-error")
    async def probe_provider_error():
        provider_client = _ProviderErrorClient()
        return await provider_client.get("/error")

    response = await client.get("/probe-provider-error")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "upstream_service_error"
    assert body["upstream"]["provider_request_id"] == "plaid-req-123"
    assert "secret upstream message" not in body["detail"]
    assert body["user_action"] == UserAction.RETRY


async def test_openapi_includes_problem_components(client):
    response = await client.get("/openapi.json")
    schema = response.json()

    assert "ProblemResponse" in schema["components"]["schemas"]
    assert "UserAction" in schema["components"]["schemas"]
    assert schema["components"]["schemas"]["UserAction"]["enum"] == [
        action.value for action in UserAction
    ]
    user_action_schema = schema["components"]["schemas"]["ProblemResponse"]["properties"][
        "user_action"
    ]
    assert any(
        option.get("$ref") == "#/components/schemas/UserAction"
        for option in user_action_schema["anyOf"]
    )
    assert "Problem400" in schema["components"]["responses"]
    assert "Problem428" in schema["components"]["responses"]
    assert "Problem504" in schema["components"]["responses"]


async def test_problem_docs_surface_default_user_action(client):
    response = await client.get("/problems/authentication-required")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["user_action"] == UserAction.REAUTHENTICATE


async def test_admin_route_can_be_authorized_with_override(app, client):
    @app.get("/probe-admin-override", dependencies=[Depends(require_roles("admin"))])
    async def probe_admin_override():
        return {"ok": True}

    app.dependency_overrides[get_auth_service] = lambda: MockAuthService(roles=["admin"])
    response = await client.get(
        "/probe-admin-override",
        headers={"authorization": "Bearer token-123"},
    )

    assert response.status_code == 200
