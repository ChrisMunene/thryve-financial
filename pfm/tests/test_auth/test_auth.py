"""Tests for authentication: delegate, service, dependencies."""

import uuid

import jwt
import pytest
from fastapi import Depends, Request

from app.auth.delegate import TokenPayload
from app.auth.mock import MockAuthDelegate
from app.auth.schemas import CurrentUser
from app.auth.service import AuthService
from app.auth.supabase import SupabaseAuthDelegate
from app.core.context import clear_current_user_id, get_current_user_id
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.dependencies import get_current_user


# --- Mock Delegate ---

class TestMockDelegate:
    async def test_returns_configured_user(self):
        delegate = MockAuthDelegate(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="chris@example.com",
            roles=["admin"],
        )
        payload = await delegate.verify_token("any-token")
        assert payload.user_id == "550e8400-e29b-41d4-a716-446655440000"
        assert payload.email == "chris@example.com"
        assert payload.roles == ["admin"]

    async def test_returns_default_user(self):
        delegate = MockAuthDelegate()
        payload = await delegate.verify_token("anything")
        assert payload.email == "test@example.com"
        assert payload.roles == ["user"]
        # user_id should be a valid UUID
        uuid.UUID(payload.user_id)

    async def test_refresh_returns_mock_token(self):
        delegate = MockAuthDelegate()
        token = await delegate.refresh_token("old-token")
        assert token == "mock-refreshed-token"


# --- Supabase Delegate ---

class TestSupabaseDelegate:
    VALID_TEST_SECRET = "test-secret-with-32-byte-minimum!!"
    WRONG_TEST_SECRET = "wrong-secret-with-32-byte-minimum!"
    CORRECT_TEST_SECRET = "correct-secret-with-32-byte-minimum"

    def _make_token(self, payload: dict, secret: str | None = None) -> str:
        secret = secret or self.VALID_TEST_SECRET
        return jwt.encode(payload, secret, algorithm="HS256")

    async def test_valid_token(self):
        delegate = SupabaseAuthDelegate()
        delegate._jwt_secret = self.VALID_TEST_SECRET

        token = self._make_token({
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "email": "user@test.com",
            "role": "user",
        })
        payload = await delegate.verify_token(token)
        assert payload.user_id == "550e8400-e29b-41d4-a716-446655440000"
        assert payload.email == "user@test.com"
        assert payload.roles == ["user"]

    async def test_expired_token(self):
        delegate = SupabaseAuthDelegate()
        delegate._jwt_secret = self.VALID_TEST_SECRET

        token = self._make_token({
            "sub": "user-1",
            "email": "user@test.com",
            "exp": 0,  # expired
        })
        with pytest.raises(AuthenticationError, match="expired"):
            await delegate.verify_token(token)

    async def test_invalid_signature(self):
        delegate = SupabaseAuthDelegate()
        delegate._jwt_secret = self.CORRECT_TEST_SECRET

        token = self._make_token({"sub": "user-1"}, secret=self.WRONG_TEST_SECRET)
        with pytest.raises(AuthenticationError, match="Invalid token"):
            await delegate.verify_token(token)

    async def test_missing_subject(self):
        delegate = SupabaseAuthDelegate()
        delegate._jwt_secret = self.VALID_TEST_SECRET

        token = self._make_token({"email": "no-sub@test.com"})
        with pytest.raises(AuthenticationError, match="missing subject"):
            await delegate.verify_token(token)

    def test_validate_configuration_requires_secret(self):
        delegate = SupabaseAuthDelegate()
        delegate._jwt_secret = ""

        with pytest.raises(RuntimeError, match="AUTH_SUPABASE_JWT_SECRET"):
            delegate.validate_configuration()


# --- Auth Service ---

class TestAuthService:
    async def test_authenticate_returns_current_user(self):
        clear_current_user_id()
        delegate = MockAuthDelegate(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            email="chris@example.com",
        )
        service = AuthService(delegate=delegate)
        user = await service.authenticate("any-token")

        assert isinstance(user, CurrentUser)
        assert str(user.user_id) == "550e8400-e29b-41d4-a716-446655440000"
        assert user.email == "chris@example.com"
        assert get_current_user_id() == "550e8400-e29b-41d4-a716-446655440000"

    async def test_authenticate_propagates_auth_error(self):
        class FailingDelegate:
            async def verify_token(self, token: str) -> TokenPayload:
                raise AuthenticationError("Token expired")
            async def refresh_token(self, token: str) -> str:
                return ""

        service = AuthService(delegate=FailingDelegate())
        with pytest.raises(AuthenticationError, match="Token expired"):
            await service.authenticate("bad-token")

    async def test_authenticate_wraps_unexpected_error(self):
        class BrokenDelegate:
            async def verify_token(self, token: str) -> TokenPayload:
                raise RuntimeError("Connection refused")
            async def refresh_token(self, token: str) -> str:
                return ""

        service = AuthService(delegate=BrokenDelegate())
        with pytest.raises(AuthenticationError, match="Authentication failed"):
            await service.authenticate("any-token")

    async def test_authenticate_does_not_set_context_for_invalid_user_id(self):
        clear_current_user_id()
        delegate = MockAuthDelegate(user_id="not-a-uuid")
        service = AuthService(delegate=delegate)

        with pytest.raises(AuthenticationError, match="Invalid user ID"):
            await service.authenticate("any-token")

        assert get_current_user_id() is None


class TestAuthDependencyContext:
    async def test_dependency_sets_request_state_user_context(self, app, client):
        @app.get("/me-context")
        async def me_context(
            request: Request,
            current_user: CurrentUser = Depends(get_current_user),
        ):
            return {
                "dependency_user_id": str(current_user.user_id),
                "state_user_id": request.state.user_id,
                "state_current_user_id": str(request.state.current_user.user_id),
            }

        response = await client.get(
            "/me-context",
            headers={"authorization": "Bearer token-123"},
        )

        assert response.status_code == 200
        assert response.json()["dependency_user_id"] == response.json()["state_user_id"]
        assert response.json()["state_current_user_id"] == response.json()["state_user_id"]

    async def test_user_context_is_cleared_between_requests(self, app, client):
        @app.get("/me-context")
        async def me_context(current_user: CurrentUser = Depends(get_current_user)):
            return {"user_id": str(current_user.user_id)}

        @app.get("/context-peek")
        async def context_peek():
            return {"current_user_id": get_current_user_id()}

        first = await client.get(
            "/me-context",
            headers={"authorization": "Bearer token-123"},
        )
        second = await client.get("/context-peek")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json() == {"current_user_id": None}


# --- CurrentUser ---

class TestCurrentUser:
    def test_user_fields(self):
        user = CurrentUser(
            user_id=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
            email="chris@example.com",
            roles=["user", "premium"],
        )
        assert user.user_id == uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        assert user.email == "chris@example.com"
        assert "premium" in user.roles

    def test_default_roles_empty(self):
        user = CurrentUser(
            user_id=uuid.uuid4(),
            email="test@test.com",
        )
        assert user.roles == []
