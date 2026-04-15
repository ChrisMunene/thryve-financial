"""Tests for the production auth facade, provider adapters, and dependencies."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, Request, Security
from jwt.utils import base64url_encode
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.auth_context import AuthContext
from app.auth.mock import MockAuthProvider
from app.auth.principal import Principal
from app.auth.repository import AuthRepository
from app.auth.service import AuthService
from app.auth.supabase import SupabaseAuthProvider, SupabaseTokenVerifier
from app.config import Settings, get_settings
from app.core.context import clear_current_user_id, get_current_anonymous_id, get_current_user_id
from app.core.exceptions import (
    AccountNotProvisionedError,
    AuthenticationRequiredError,
    DependencyUnavailableError,
)
from app.dependencies import require_auth, require_user
from app.models import AuthIdentityRecord, User
from app.models.base import Base


def _encode_int(value: int) -> str:
    return base64url_encode(
        value.to_bytes((value.bit_length() + 7) // 8, "big")
    ).decode()


def _generate_rsa_keypair(*, kid: str = "test-key") -> tuple[object, object, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _encode_int(public_numbers.n),
        "e": _encode_int(public_numbers.e),
    }
    return private_key, public_key, jwk


def _base_claims(**overrides) -> dict[str, object]:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "https://test.supabase.co/auth/v1",
        "aud": "authenticated",
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "exp": now + 3600,
        "iat": now,
        "email": "user@test.com",
        "role": "user",
        "scope": "transactions:import",
    }
    claims.update(overrides)
    return claims


def _encode_token(
    private_key: object,
    *,
    claims: dict[str, object],
    kid: str = "test-key",
) -> str:
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


class _StaticJwksCache:
    def __init__(self, keys: dict[str, object]) -> None:
        self._keys = keys

    async def get_signing_key(self, kid: str) -> object:
        key = self._keys.get(kid)
        if key is None:
            raise AuthenticationRequiredError.invalid_token(jwt_error_type="UnknownKeyId")
        return key


@pytest.fixture
async def auth_session_factory():
    # Import mapped classes before metadata creation.
    _ = (User, AuthIdentityRecord)

    schema_name = f"test_auth_{uuid.uuid4().hex}"
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


class TestSupabaseTokenVerifier:
    def _build_verifier(self, *, audience: str = "authenticated") -> tuple[SupabaseTokenVerifier, object]:
        private_key, public_key, _ = _generate_rsa_keypair()
        settings = Settings(
            environment="development",
            auth={
                "supabase_url": "https://test.supabase.co",
                "audience": audience,
                "supabase_anon_key": "anon-test-key",
                "accepted_algorithms": ["RS256"],
            },
        )
        verifier = SupabaseTokenVerifier(
            settings=settings,
            jwks_cache=_StaticJwksCache({"test-key": public_key}),
        )
        return verifier, private_key

    async def test_valid_token(self):
        verifier, private_key = self._build_verifier()
        token = _encode_token(private_key, claims=_base_claims())

        claims = await verifier.verify_access_token(token)

        assert claims.subject_id == "550e8400-e29b-41d4-a716-446655440000"
        assert claims.email == "user@test.com"
        assert claims.roles == ["user"]
        assert claims.scopes == ["transactions:import"]

    async def test_expired_token(self):
        verifier, private_key = self._build_verifier()
        token = _encode_token(private_key, claims=_base_claims(exp=int(time.time()) - 120))

        with pytest.raises(AuthenticationRequiredError) as exc_info:
            await verifier.verify_access_token(token)

        assert exc_info.value.extra_log_context["auth_reason"] == "token_expired"

    async def test_missing_subject_claim_is_rejected(self):
        verifier, private_key = self._build_verifier()
        claims = _base_claims()
        claims.pop("sub")
        token = _encode_token(private_key, claims=claims)

        with pytest.raises(AuthenticationRequiredError) as exc_info:
            await verifier.verify_access_token(token)

        assert exc_info.value.extra_log_context["auth_reason"] == "invalid_token"
        assert exc_info.value.extra_log_context["jwt_error_type"] == "MissingRequiredClaimError"

    async def test_wrong_audience_is_rejected(self):
        verifier, private_key = self._build_verifier()
        token = _encode_token(private_key, claims=_base_claims(aud="mobile-app"))

        with pytest.raises(AuthenticationRequiredError) as exc_info:
            await verifier.verify_access_token(token)

        assert exc_info.value.extra_log_context["auth_reason"] == "invalid_token"
        assert exc_info.value.extra_log_context["jwt_error_type"] == "InvalidAudienceError"

    async def test_unknown_key_id_is_rejected(self):
        verifier, private_key = self._build_verifier()
        token = _encode_token(private_key, claims=_base_claims(), kid="rotated-key")

        with pytest.raises(AuthenticationRequiredError) as exc_info:
            await verifier.verify_access_token(token)

        assert exc_info.value.extra_log_context["auth_reason"] == "invalid_token"
        assert exc_info.value.extra_log_context["jwt_error_type"] == "UnknownKeyId"

    def test_validate_configuration_requires_resolved_issuer(self):
        settings = Settings(
            environment="development",
            auth={"audience": "authenticated", "supabase_anon_key": "anon-test-key"},
        )
        verifier = SupabaseTokenVerifier(
            settings=settings,
            jwks_cache=_StaticJwksCache({}),
        )

        with pytest.raises(RuntimeError, match="AUTH_ISSUER or AUTH_SUPABASE_URL"):
            verifier.validate_configuration()

    def test_validate_configuration_requires_audience(self):
        settings = Settings(
            environment="development",
            auth={
                "supabase_url": "https://test.supabase.co",
                "supabase_anon_key": "anon-test-key",
            },
        )
        verifier = SupabaseTokenVerifier(
            settings=settings,
            jwks_cache=_StaticJwksCache({}),
        )

        with pytest.raises(RuntimeError, match="AUTH_AUDIENCE"):
            verifier.validate_configuration()


class TestSupabaseAuthProvider:
    @staticmethod
    def _settings(*, anon_key: str = "anon-test-key") -> Settings:
        return Settings(
            environment="development",
            auth={
                "supabase_url": "https://test.supabase.co",
                "audience": "authenticated",
                "supabase_anon_key": anon_key,
                "accepted_algorithms": ["RS256"],
            },
        )

    async def test_sign_in_with_password_normalizes_provider_session(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["apikey"] == "anon-test-key"
            assert request.url.path == "/auth/v1/token"
            assert request.url.params["grant_type"] == "password"
            return httpx.Response(
                200,
                json={
                    "access_token": "provider-access-token",
                    "refresh_token": "provider-refresh-token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "user": {
                        "id": "provider-user-123",
                        "email": "user@test.com",
                        "email_confirmed_at": "2025-01-01T00:00:00Z",
                        "last_sign_in_at": "2025-01-02T00:00:00Z",
                        "user_metadata": {"display_name": "Test User"},
                    },
                },
            )

        provider = SupabaseAuthProvider(
            settings=self._settings(),
            transport=httpx.MockTransport(handler),
        )

        session = await provider.sign_in_with_password(
            email="user@test.com",
            password="secret-password",
        )

        assert session.access_token == "provider-access-token"
        assert session.refresh_token == "provider-refresh-token"
        assert session.user.subject_id == "provider-user-123"
        assert session.user.issuer == "https://test.supabase.co/auth/v1"
        assert session.user.display_name == "Test User"
        assert session.user.email == "user@test.com"

    def test_validate_configuration_requires_anon_key(self):
        provider = SupabaseAuthProvider(
            settings=self._settings(anon_key=""),
            jwks_cache=_StaticJwksCache({}),
        )

        with pytest.raises(RuntimeError, match="AUTH_SUPABASE_ANON_KEY"):
            provider.validate_configuration()


class TestAuthService:
    async def test_sign_in_with_password_provisions_local_user_and_identity(
        self,
        auth_session_factory,
    ):
        subject_id = str(uuid.uuid4())
        issuer = "https://test.supabase.co/auth/v1"
        provider = MockAuthProvider(
            subject_id=subject_id,
            issuer=issuer,
            email="chris@example.com",
            display_name="Chris",
            roles=["admin"],
            scopes=["transactions:import", "transactions:read"],
        )
        service = AuthService(provider=provider, session_factory=auth_session_factory)

        result = await service.sign_in_with_password(
            email="chris@example.com",
            password="secret-password",
        )

        assert result.user.email == "chris@example.com"
        assert result.user.display_name == "Chris"
        assert result.user.roles == ["admin"]
        assert result.user.scopes == ["transactions:import", "transactions:read"]

        async with auth_session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_email("chris@example.com")
            identity = await repo.get_identity(
                provider="mock",
                issuer=issuer,
                subject_id=subject_id,
            )

        assert user is not None
        assert identity is not None
        assert identity.user_id == user.id

    async def test_authenticate_request_returns_principal_for_provisioned_identity(
        self,
        auth_session_factory,
    ):
        clear_current_user_id()
        subject_id = str(uuid.uuid4())
        provider = MockAuthProvider(
            subject_id=subject_id,
            email="chris@example.com",
            scopes=["transactions:import"],
        )
        service = AuthService(provider=provider, session_factory=auth_session_factory)
        auth_session = await service.sign_in_with_password(
            email="chris@example.com",
            password="secret-password",
        )

        principal = await service.authenticate_request("mock-access-token")

        assert isinstance(principal, Principal)
        assert principal.subject_id == subject_id
        assert principal.user_id == auth_session.user.id
        assert principal.email == "chris@example.com"
        assert get_current_user_id() == str(auth_session.user.id)

    async def test_authenticate_request_rejects_unprovisioned_identity(self, auth_session_factory):
        clear_current_user_id()
        provider = MockAuthProvider(subject_id="provider|user-123")
        service = AuthService(provider=provider, session_factory=auth_session_factory)

        with pytest.raises(AccountNotProvisionedError):
            await service.authenticate_request("mock-access-token")

        assert get_current_user_id() is None

    async def test_sign_up_pending_verification_does_not_provision_local_user(
        self,
        auth_session_factory,
    ):
        provider = MockAuthProvider(
            email="pending@example.com",
            requires_email_verification=True,
        )
        service = AuthService(provider=provider, session_factory=auth_session_factory)

        result = await service.sign_up_with_password(
            email="pending@example.com",
            password="secret-password",
            display_name="Pending User",
        )

        assert result.requires_email_verification is True
        assert result.session is None
        assert result.user is None

        async with auth_session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_email("pending@example.com")

        assert user is None

    async def test_confirm_email_verification_provisions_local_user(self, auth_session_factory):
        subject_id = str(uuid.uuid4())
        issuer = "https://test.supabase.co/auth/v1"
        provider = MockAuthProvider(
            subject_id=subject_id,
            issuer=issuer,
            email="verified@example.com",
            requires_email_verification=True,
        )
        service = AuthService(provider=provider, session_factory=auth_session_factory)

        result = await service.confirm_email_verification(
            email="verified@example.com",
            token="verification-token",
        )

        assert result.message == "Your email address has been verified."

        async with auth_session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_email("verified@example.com")
            identity = await repo.get_identity(
                provider="mock",
                issuer=issuer,
                subject_id=subject_id,
            )

        assert user is not None
        assert identity is not None

    async def test_get_current_user_returns_linked_application_user(self, auth_session_factory):
        provider = MockAuthProvider(email="current@example.com")
        service = AuthService(provider=provider, session_factory=auth_session_factory)
        auth_session = await service.sign_in_with_password(
            email="current@example.com",
            password="secret-password",
        )

        current_user = await service.get_current_user(user_id=auth_session.user.id)

        assert current_user.id == auth_session.user.id
        assert current_user.email == "current@example.com"
        assert current_user.identities[0].provider == "mock"

    async def test_duplicate_identity_mapping_is_rejected(self, auth_session_factory):
        subject_id = str(uuid.uuid4())
        issuer = "https://test.supabase.co/auth/v1"

        async with auth_session_factory() as session:
            async with session.begin():
                repo = AuthRepository(session)
                user = await repo.create_user(email="duplicate@example.com")
                await repo.create_identity(
                    user_id=user.id,
                    provider="mock",
                    issuer=issuer,
                    subject_id=subject_id,
                    email="duplicate@example.com",
                    email_verified_at=None,
                    last_sign_in_at=None,
                    provider_metadata={},
                )

            with pytest.raises(IntegrityError):
                async with session.begin():
                    repo = AuthRepository(session)
                    await repo.create_identity(
                        user_id=user.id,
                        provider="mock",
                        issuer=issuer,
                        subject_id=subject_id,
                        email="duplicate@example.com",
                        email_verified_at=None,
                        last_sign_in_at=None,
                        provider_metadata={},
                    )

    async def test_provider_errors_are_normalized(self, auth_session_factory):
        class BrokenProvider(MockAuthProvider):
            async def sign_in_with_password(
                self,
                *,
                email: str,
                password: str,
            ):
                del email, password
                raise RuntimeError("provider is down")

        service = AuthService(provider=BrokenProvider(), session_factory=auth_session_factory)

        with pytest.raises(DependencyUnavailableError) as exc_info:
            await service.sign_in_with_password(
                email="chris@example.com",
                password="secret-password",
            )

        assert exc_info.value.extra_log_context["auth_reason"] == "provider_error"
        assert exc_info.value.extra_log_context["auth_operation"] == "sign_in_with_password"


class TestAuthDependencyContext:
    async def test_dependency_sets_request_state_principal_context(self, app, client):
        @app.get("/me-context")
        async def me_context(
            request: Request,
            principal: Principal = Security(require_auth),
        ):
            return {
                "dependency_subject_id": principal.subject_id,
                "state_subject_id": request.state.subject_id,
                "state_principal_subject_id": request.state.principal.subject_id,
            }

        response = await client.get(
            "/me-context",
            headers={"authorization": "Bearer token-123"},
        )

        assert response.status_code == 200
        assert response.json()["dependency_subject_id"] == response.json()["state_subject_id"]
        assert response.json()["state_principal_subject_id"] == response.json()["state_subject_id"]

    async def test_require_user_loads_authenticated_user_and_principal(self, app, client):
        @app.get("/current-user")
        async def current_user_route(auth_context: AuthContext = Depends(require_user)):
            return {
                "user_id": str(auth_context.user.id),
                "email": auth_context.user.email,
                "identity_provider": auth_context.user.identities[0].provider,
                "subject_id": auth_context.principal.subject_id,
            }

        response = await client.get(
            "/current-user",
            headers={"authorization": "Bearer token-123"},
        )

        assert response.status_code == 200
        assert response.json()["email"] == "test@example.com"
        assert response.json()["identity_provider"] == "mock"
        assert response.json()["subject_id"]
        uuid.UUID(response.json()["user_id"])

    async def test_user_context_is_cleared_between_requests(self, app, client):
        @app.get("/me-context")
        async def me_context(principal: Principal = Security(require_auth)):
            return {"subject_id": principal.subject_id}

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

    async def test_anonymous_context_is_hydrated_and_cleared_between_requests(self, app, client):
        @app.get("/anonymous-context")
        async def anonymous_context():
            return {"anonymous_id": get_current_anonymous_id()}

        first = await client.get(
            "/anonymous-context",
            headers={"X-Anonymous-ID": "anon-123"},
        )
        second = await client.get("/anonymous-context")
        invalid = await client.get(
            "/anonymous-context",
            headers={"X-Anonymous-ID": "not valid"},
        )

        assert first.status_code == 200
        assert first.json() == {"anonymous_id": "anon-123"}
        assert second.status_code == 200
        assert second.json() == {"anonymous_id": None}
        assert invalid.status_code == 200
        assert invalid.json() == {"anonymous_id": None}

    async def test_openapi_surfaces_bearer_security_scheme(self, client):
        response = await client.get("/openapi.json")
        schema = response.json()

        assert schema["components"]["securitySchemes"]["BearerAuth"]["type"] == "http"
        assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
        assert schema["paths"]["/api/v1/transactions/import"]["post"]["security"] == [
            {"BearerAuth": []}
        ]
        assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [
            {"BearerAuth": []}
        ]


class TestArchitecture:
    def test_only_auth_wiring_imports_provider_internals_outside_auth_package(self):
        repo_root = Path(__file__).resolve().parents[2]
        app_root = repo_root / "app"
        allowed = {app_root / "dependencies.py"}
        import_targets = (
            "app.auth.provider",
            "app.auth.supabase",
            "app.auth.verifier",
            "app.auth.jwks",
        )

        offenders: list[str] = []
        for path in app_root.rglob("*.py"):
            if path.is_relative_to(app_root / "auth"):
                continue
            if path in allowed:
                continue

            source = path.read_text()
            if any(target in source for target in import_targets):
                offenders.append(str(path.relative_to(repo_root)))

        assert offenders == []


class TestPrincipal:
    def test_principal_fields(self):
        principal = Principal(
            subject_id="550e8400-e29b-41d4-a716-446655440000",
            user_id=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
            email="chris@example.com",
            roles=["user", "premium"],
        )
        assert principal.user_id == uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        assert principal.subject_id == "550e8400-e29b-41d4-a716-446655440000"
        assert "premium" in principal.roles

    def test_default_roles_empty(self):
        principal = Principal(
            subject_id=str(uuid.uuid4()),
            user_id=uuid.uuid4(),
            email="test@test.com",
        )
        assert principal.roles == []
