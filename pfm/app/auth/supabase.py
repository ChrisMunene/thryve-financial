"""Supabase auth provider implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.auth.claims import VerifiedClaims
from app.auth.jwks import JwksCache
from app.auth.provider import (
    AuthProvider,
    ProviderSession,
    ProviderSignUpResult,
    ProviderUserProfile,
)
from app.auth.verifier import JwtVerifier
from app.config import Settings, get_settings
from app.core.context import get_correlation_id
from app.core.exceptions import (
    DependencyUnavailableError,
    InvalidCredentialsError,
    InvalidVerificationCodeError,
    UpstreamTimeoutError,
)

logger = structlog.get_logger()


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


class SupabaseTokenVerifier:
    """Strict Supabase access-token verifier using issuer metadata and JWKS."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        jwks_cache: JwksCache | None = None,
    ) -> None:
        runtime_settings = settings or get_settings()
        auth_settings = runtime_settings.auth

        self._issuer = auth_settings.resolved_issuer
        self._jwks_url = auth_settings.resolved_jwks_url
        self._audience = auth_settings.audience
        self._algorithms = tuple(auth_settings.accepted_algorithms)
        self._required_claims = tuple(auth_settings.required_claims)
        self._jwks_cache = jwks_cache or JwksCache(
            jwks_url=self._jwks_url,
            cache_ttl_seconds=auth_settings.jwks_cache_ttl_seconds,
            refresh_timeout_seconds=auth_settings.jwks_refresh_timeout_seconds,
        )
        self._verifier = JwtVerifier(
            issuer=self._issuer,
            audience=self._audience,
            algorithms=self._algorithms,
            required_claims=self._required_claims,
            clock_skew_seconds=auth_settings.clock_skew_seconds,
            jwks_cache=self._jwks_cache,
        )

    async def verify_access_token(self, access_token: str) -> VerifiedClaims:
        return await self._verifier.verify_token(access_token)

    def validate_configuration(self) -> None:
        self._verifier.validate_configuration()
        if not self._jwks_url:
            raise RuntimeError(
                "AUTH_SUPABASE_JWKS_URL or AUTH_SUPABASE_URL is required for auth readiness"
            )


class SupabaseAuthProvider(AuthProvider):
    """Supabase-backed auth provider for password and session flows."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        jwks_cache: JwksCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        runtime_settings = settings or get_settings()
        auth_settings = runtime_settings.auth

        self._settings = runtime_settings
        self._auth_base_url = auth_settings.resolved_issuer
        self._anon_key = auth_settings.supabase_anon_key.get_secret_value()
        self._transport = transport
        self._token_verifier = SupabaseTokenVerifier(
            settings=runtime_settings,
            jwks_cache=jwks_cache,
        )

    @property
    def name(self) -> str:
        return "supabase"

    async def verify_access_token(self, access_token: str) -> VerifiedClaims:
        return await self._token_verifier.verify_access_token(access_token)

    async def sign_up_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> ProviderSignUpResult:
        payload: dict[str, Any] = {"email": email, "password": password}
        if display_name:
            payload["data"] = {"display_name": display_name}

        data = await self._request_json("POST", "/signup", json=payload)
        session = self._parse_provider_session(data)
        user_payload = data.get("user")
        user = self._parse_provider_user(user_payload) if isinstance(user_payload, dict) else None
        requires_email_verification = session is None

        return ProviderSignUpResult(
            user=user,
            session=session,
            requires_email_verification=requires_email_verification,
        )

    async def sign_in_with_password(
        self,
        *,
        email: str,
        password: str,
    ) -> ProviderSession:
        data = await self._request_json(
            "POST",
            "/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
        )
        return self._parse_provider_session(data)

    async def refresh_session(self, *, refresh_token: str) -> ProviderSession:
        data = await self._request_json(
            "POST",
            "/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
        )
        return self._parse_provider_session(data)

    async def request_password_reset(
        self,
        *,
        email: str,
        redirect_to: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"email": email}
        if redirect_to:
            payload["redirect_to"] = redirect_to

        await self._request_json(
            "POST",
            "/recover",
            json=payload,
            allow_expected_client_errors=True,
        )

    async def confirm_password_reset(
        self,
        *,
        email: str,
        token: str,
        new_password: str,
    ) -> None:
        verification = await self._request_json(
            "POST",
            "/verify",
            json={"email": email, "token": token, "type": "recovery"},
            invalid_client_error=InvalidVerificationCodeError.default(),
        )
        session = self._parse_provider_session(verification)
        await self._request_json(
            "PUT",
            "/user",
            json={"password": new_password},
            access_token=session.access_token,
        )

    async def request_email_verification(
        self,
        *,
        email: str,
        redirect_to: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"email": email, "type": "signup"}
        if redirect_to:
            payload["options"] = {"email_redirect_to": redirect_to}

        await self._request_json(
            "POST",
            "/resend",
            json=payload,
            allow_expected_client_errors=True,
        )

    async def confirm_email_verification(
        self,
        *,
        email: str,
        token: str,
    ) -> ProviderUserProfile:
        verification = await self._request_json(
            "POST",
            "/verify",
            json={"email": email, "token": token, "type": "email"},
            invalid_client_error=InvalidVerificationCodeError.default(),
        )
        session = self._parse_provider_session(verification)
        return session.user

    async def logout(self, *, access_token: str) -> None:
        await self._request_json(
            "POST",
            "/logout",
            access_token=access_token,
            allow_expected_client_errors=True,
        )

    def validate_configuration(self) -> None:
        self._token_verifier.validate_configuration()
        if not self._auth_base_url:
            raise RuntimeError("AUTH_SUPABASE_URL or AUTH_ISSUER is required for auth readiness")
        if not self._anon_key:
            raise RuntimeError("AUTH_SUPABASE_ANON_KEY is required for auth readiness")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
        allow_expected_client_errors: bool = False,
        invalid_client_error: Exception | None = None,
    ) -> dict[str, Any]:
        headers = {
            "apikey": self._anon_key,
            "content-type": "application/json",
        }
        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Request-ID"] = correlation_id
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        try:
            async with httpx.AsyncClient(
                base_url=self._auth_base_url,
                timeout=10.0,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError.for_service("auth") from exc
        except httpx.HTTPError as exc:
            raise DependencyUnavailableError.for_service("auth") from exc

        payload = self._parse_response_payload(response)
        if response.status_code >= 500:
            raise DependencyUnavailableError.for_service("auth")
        if response.status_code >= 400:
            if allow_expected_client_errors:
                logger.info(
                    "auth.provider.client_error_suppressed",
                    provider=self.name,
                    status_code=response.status_code,
                    path=path,
                )
                return payload

            if invalid_client_error is not None:
                raise invalid_client_error

            raise self._client_error(path=path, payload=payload)

        return payload

    @staticmethod
    def _parse_response_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _client_error(*, path: str, payload: dict[str, Any]) -> Exception:
        message = str(
            payload.get("msg")
            or payload.get("message")
            or payload.get("error_description")
            or payload.get("error")
            or ""
        ).lower()
        if path in {"/token", "/logout"}:
            return InvalidCredentialsError.default(detail="The session is invalid or expired.")
        if path == "/signup" and "already registered" in message:
            from app.core.exceptions import ConflictError

            return ConflictError.already_exists(
                "user",
                detail="An account with that email already exists.",
            )
        if "invalid" in message or "expired" in message:
            return InvalidCredentialsError.default()
        return InvalidCredentialsError.default()

    def _parse_provider_user(self, payload: dict[str, Any]) -> ProviderUserProfile:
        user_metadata = payload.get("user_metadata")
        metadata = user_metadata if isinstance(user_metadata, dict) else {}
        display_name = None
        for key in ("display_name", "full_name", "name"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                display_name = value.strip()
                break

        subject_id = str(payload.get("id") or payload.get("sub") or "").strip()
        if not subject_id:
            raise DependencyUnavailableError.for_service(
                "auth",
                detail="Authentication is temporarily unavailable.",
            )

        return ProviderUserProfile(
            subject_id=subject_id,
            issuer=self._settings.auth.resolved_issuer,
            email=payload.get("email"),
            email_verified_at=(
                _parse_datetime(payload.get("email_confirmed_at"))
                or _parse_datetime(payload.get("confirmed_at"))
            ),
            display_name=display_name,
            last_sign_in_at=_parse_datetime(payload.get("last_sign_in_at")),
            metadata=metadata,
            raw_user=dict(payload),
        )

    def _parse_provider_session(self, payload: dict[str, Any]) -> ProviderSession:
        user_payload = payload.get("user")
        if not isinstance(user_payload, dict):
            raise DependencyUnavailableError.for_service(
                "auth",
                detail="Authentication is temporarily unavailable.",
            )

        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise DependencyUnavailableError.for_service(
                "auth",
                detail="Authentication is temporarily unavailable.",
            )

        return ProviderSession(
            access_token=access_token,
            refresh_token=(
                str(payload["refresh_token"])
                if payload.get("refresh_token") is not None
                else None
            ),
            token_type=str(payload.get("token_type") or "bearer"),
            expires_in=(
                int(payload["expires_in"])
                if payload.get("expires_in") is not None
                else None
            ),
            user=self._parse_provider_user(user_payload),
        )
