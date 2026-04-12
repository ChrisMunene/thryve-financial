"""Tests for security middleware: headers, CORS, correlation ID in responses."""

from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AuthenticationRequiredError


class TestSecurityHeaders:
    async def test_x_content_type_options(self, client):
        response = await client.get("/api/v1/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    async def test_x_frame_options(self, client):
        response = await client.get("/api/v1/health")
        assert response.headers.get("x-frame-options") == "DENY"

    async def test_x_request_id_in_response(self, client):
        response = await client.get("/api/v1/health")
        assert "x-request-id" in response.headers
        # Should be a UUID
        rid = response.headers["x-request-id"]
        assert len(rid) == 36

    async def test_accepts_x_request_id_from_client(self, client):
        response = await client.get(
            "/api/v1/health",
            headers={"x-request-id": "custom-123"},
        )
        assert response.headers["x-request-id"] == "custom-123"

    async def test_invalid_x_request_id_is_replaced(self, client):
        response = await client.get(
            "/api/v1/health",
            headers={"x-request-id": "not valid"},
        )
        assert response.headers["x-request-id"] != "not valid"
        assert len(response.headers["x-request-id"]) == 36

    async def test_no_hsts_in_development(self, client):
        response = await client.get("/api/v1/health")
        assert "strict-transport-security" not in response.headers

    async def test_cors_exposes_x_request_id(self, client):
        response = await client.get(
            "/api/v1/health",
            headers={"origin": "http://localhost:3000"},
        )
        assert response.headers["access-control-expose-headers"] == (
            "X-Request-ID, Idempotent-Replayed"
        )


class TestCorrelationErrorResponses:
    async def test_handled_error_includes_x_request_id_header(self, app, client):
        @app.get("/handled-correlation-error")
        async def handled_error():
            raise AuthenticationRequiredError.default()

        response = await client.get("/handled-correlation-error")

        assert response.status_code == 401
        assert "x-request-id" in response.headers
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert response.headers["www-authenticate"] == "Bearer"

    async def test_unhandled_error_includes_x_request_id_header(self, app, client):
        @app.get("/unhandled-correlation-error")
        async def unhandled_error():
            raise RuntimeError("boom")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/unhandled-correlation-error")

        assert response.status_code == 500
        assert "x-request-id" in response.headers
        assert response.json()["request_id"] == response.headers["x-request-id"]

    async def test_unhandled_error_keeps_cors_headers(self, app):
        @app.get("/cors-unhandled-error")
        async def cors_unhandled_error():
            raise RuntimeError("boom")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get(
                "/cors-unhandled-error",
                headers={"origin": "http://localhost:3000"},
            )

        assert response.status_code == 500
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
