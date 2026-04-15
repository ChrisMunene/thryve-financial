"""Mock auth service and provider implementations for tests."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Literal

from app.auth.claims import VerifiedClaims
from app.auth.principal import Principal
from app.auth.provider import (
    AuthProvider,
    ProviderSession,
    ProviderSignUpResult,
    ProviderUserProfile,
)
from app.auth.types import (
    AuthActionResult,
    AuthIdentity,
    AuthSession,
    AuthenticatedUser,
    PasswordSignUpResult,
)


class MockAuthProvider(AuthProvider):
    """Simple provider double used by unit tests."""

    def __init__(
        self,
        *,
        subject_id: str | None = None,
        email: str = "test@example.com",
        display_name: str | None = "Test User",
        roles: list[str] | None = None,
        scopes: list[str] | None = None,
        issuer: str = "https://test.supabase.co/auth/v1",
        audience: str = "authenticated",
        access_token: str = "mock-access-token",
        refresh_token: str = "mock-refresh-token",
        requires_email_verification: bool = False,
    ) -> None:
        self._subject_id = subject_id or str(uuid.uuid4())
        self._email = email
        self._display_name = display_name
        self._roles = roles or ["user"]
        self._scopes = scopes or ["transactions:import"]
        self._issuer = issuer
        self._audience = audience
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._requires_email_verification = requires_email_verification

    @property
    def name(self) -> str:
        return "mock"

    async def verify_access_token(self, access_token: str) -> VerifiedClaims:
        now = int(time.time())
        return VerifiedClaims(
            subject_id=self._subject_id,
            issuer=self._issuer,
            audience=self._audience,
            expires_at=now + 3600,
            issued_at=now,
            email=self._email,
            roles=self._roles,
            scopes=self._scopes,
            session_id="mock-session-id",
        )

    async def sign_up_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> ProviderSignUpResult:
        del password
        user = self._provider_user(email=email, display_name=display_name)
        session = None
        if not self._requires_email_verification:
            session = self._provider_session(user)
        return ProviderSignUpResult(
            user=user,
            session=session,
            requires_email_verification=self._requires_email_verification,
        )

    async def sign_in_with_password(
        self,
        *,
        email: str,
        password: str,
    ) -> ProviderSession:
        del password
        return self._provider_session(self._provider_user(email=email))

    async def refresh_session(self, *, refresh_token: str) -> ProviderSession:
        del refresh_token
        return self._provider_session(self._provider_user())

    async def request_password_reset(
        self,
        *,
        email: str,
        redirect_to: str | None = None,
    ) -> None:
        del email, redirect_to

    async def confirm_password_reset(
        self,
        *,
        email: str,
        token: str,
        new_password: str,
    ) -> None:
        del email, token, new_password

    async def request_email_verification(
        self,
        *,
        email: str,
        redirect_to: str | None = None,
    ) -> None:
        del email, redirect_to

    async def confirm_email_verification(
        self,
        *,
        email: str,
        token: str,
    ) -> ProviderUserProfile:
        del token
        return self._provider_user(email=email)

    async def logout(self, *, access_token: str) -> None:
        del access_token

    def validate_configuration(self) -> None:
        return None

    def _provider_user(
        self,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> ProviderUserProfile:
        return ProviderUserProfile(
            subject_id=self._subject_id,
            issuer=self._issuer,
            email=email or self._email,
            email_verified_at=datetime.now(UTC),
            display_name=display_name or self._display_name,
            last_sign_in_at=datetime.now(UTC),
            metadata={},
            raw_user={},
        )

    def _provider_session(self, user: ProviderUserProfile) -> ProviderSession:
        return ProviderSession(
            access_token=self._access_token,
            refresh_token=self._refresh_token,
            token_type="bearer",
            expires_in=3600,
            user=user,
        )


class MockAuthService:
    """Simple auth facade double used by route and contract tests."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID | None = None,
        subject_id: str | None = None,
        email: str = "test@example.com",
        display_name: str | None = "Test User",
        roles: list[str] | None = None,
        scopes: list[str] | None = None,
        actor_type: Literal["user", "service_account"] = "user",
        provider_name: str = "mock",
        requires_email_verification: bool = False,
    ) -> None:
        self._user_id = user_id or uuid.uuid4()
        self._subject_id = subject_id or str(uuid.uuid4())
        self._email = email
        self._display_name = display_name
        self._roles = roles or ["user"]
        self._scopes = scopes or ["transactions:import"]
        self._actor_type = actor_type
        self._provider_name = provider_name
        self._requires_email_verification = requires_email_verification

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def authenticate_request(self, access_token: str) -> Principal:
        del access_token
        return Principal(
            subject_id=self._subject_id,
            user_id=self._user_id,
            actor_type=self._actor_type,
            session_id="mock-session-id",
            issuer="https://test.supabase.co/auth/v1",
            audience="authenticated",
            email=self._email,
            roles=list(self._roles),
            scopes=list(self._scopes),
            metadata={},
        )

    async def sign_up_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> PasswordSignUpResult:
        del password
        if self._requires_email_verification:
            return PasswordSignUpResult(
                email=email,
                requires_email_verification=True,
                session=None,
                user=None,
            )
        session = await self.sign_in_with_password(
            email=email,
            password="mock-password",
        )
        if display_name is not None:
            session.user.display_name = display_name
        return PasswordSignUpResult(
            email=email,
            requires_email_verification=False,
            session=session,
            user=session.user,
        )

    async def sign_in_with_password(self, *, email: str, password: str) -> AuthSession:
        del password
        user = self._authenticated_user(email=email)
        return AuthSession(
            access_token="mock-access-token",
            refresh_token="mock-refresh-token",
            token_type="bearer",
            expires_in=3600,
            user=user,
        )

    async def refresh_session(self, *, refresh_token: str) -> AuthSession:
        del refresh_token
        return await self.sign_in_with_password(email=self._email, password="mock-password")

    async def request_password_reset(self, *, email: str) -> AuthActionResult:
        del email
        return AuthActionResult(
            message="If an account exists for that email, reset instructions have been sent."
        )

    async def confirm_password_reset(
        self,
        *,
        email: str,
        token: str,
        new_password: str,
    ) -> AuthActionResult:
        del email, token, new_password
        return AuthActionResult(message="Your password has been updated.")

    async def request_email_verification(self, *, email: str) -> AuthActionResult:
        del email
        return AuthActionResult(
            message="If an account exists for that email, verification instructions have been sent."
        )

    async def confirm_email_verification(
        self,
        *,
        email: str,
        token: str,
    ) -> AuthActionResult:
        del email, token
        return AuthActionResult(message="Your email address has been verified.")

    async def logout(self, *, access_token: str) -> AuthActionResult:
        del access_token
        return AuthActionResult(message="You have been signed out.")

    async def get_current_user(
        self,
        *,
        user_id: uuid.UUID,
        principal: Principal | None = None,
    ) -> AuthenticatedUser:
        del user_id
        user = self._authenticated_user(email=self._email)
        if principal is not None:
            user.roles = list(principal.roles)
            user.scopes = list(principal.scopes)
            user.actor_type = principal.actor_type
            user.tenant_id = principal.tenant_id
        return user

    def validate_configuration(self) -> None:
        return None

    def _authenticated_user(self, *, email: str) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=self._user_id,
            email=email,
            display_name=self._display_name,
            email_verified_at=datetime.now(UTC),
            is_active=True,
            tenant_id=None,
            actor_type=self._actor_type,
            roles=list(self._roles),
            scopes=list(self._scopes),
            identities=[
                AuthIdentity(
                    provider=self._provider_name,
                    issuer="https://test.supabase.co/auth/v1",
                    subject_id=self._subject_id,
                    email=email,
                    email_verified_at=datetime.now(UTC),
                    last_sign_in_at=datetime.now(UTC),
                    metadata={},
                )
            ],
        )
