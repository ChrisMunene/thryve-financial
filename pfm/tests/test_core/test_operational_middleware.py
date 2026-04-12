"""Tests for request timeout and body size middleware."""

import asyncio

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.middleware.operational import BodySizeLimitMiddleware, RequestTimeoutMiddleware


class TestRequestTimeoutMiddleware:
    async def test_returns_timeout_error(self):
        app = FastAPI()
        app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=0.5)

        @app.get("/slow")
        async def slow():
            await asyncio.sleep(5)
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/slow")

        assert response.status_code == 503
        assert response.json()["code"] == "request_deadline_exceeded"
        assert response.json()["retryable"] is True


class TestBodySizeLimitMiddleware:
    async def test_rejects_large_body(self):
        app = FastAPI()
        app.add_middleware(BodySizeLimitMiddleware, max_body_size=8)

        @app.post("/echo")
        async def echo(request: Request):
            return {"body": (await request.body()).decode("utf-8")}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post("/echo", content=b"123456789")

        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"

    async def test_allows_body_within_limit(self):
        app = FastAPI()
        app.add_middleware(BodySizeLimitMiddleware, max_body_size=16)

        @app.post("/echo")
        async def echo(request: Request):
            return {"body": (await request.body()).decode("utf-8")}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post("/echo", content=b"12345678")

        assert response.status_code == 200
        assert response.json() == {"body": "12345678"}
