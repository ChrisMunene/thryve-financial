"""Internal auth provider contracts and provider-facing DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.auth.claims import VerifiedClaims


class ProviderUserProfile(BaseModel):
    """Normalized user profile returned by an auth provider."""

    subject_id: str
    issuer: str
    email: str | None = None
    email_verified_at: datetime | None = None
    display_name: str | None = None
    last_sign_in_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_user: dict[str, Any] = Field(default_factory=dict)


class ProviderSession(BaseModel):
    """Normalized provider session returned by sign-in and refresh flows."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    user: ProviderUserProfile


class ProviderSignUpResult(BaseModel):
    """Provider response for password sign-up."""

    user: ProviderUserProfile | None = None
    session: ProviderSession | None = None
    requires_email_verification: bool = False


@runtime_checkable
class AuthProvider(Protocol):
    """Internal vendor adapter consumed only by the auth subsystem."""

    @property
    def name(self) -> str:
        """Stable provider name for logging and identity mapping."""
        ...

    async def verify_access_token(self, access_token: str) -> VerifiedClaims:
        """Verify an access token and return normalized claims."""
        ...

    async def sign_up_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> ProviderSignUpResult:
        """Create a provider account using email/password credentials."""
        ...

    async def sign_in_with_password(
        self,
        *,
        email: str,
        password: str,
    ) -> ProviderSession:
        """Exchange email/password credentials for a provider session."""
        ...

    async def refresh_session(self, *, refresh_token: str) -> ProviderSession:
        """Exchange a refresh token for a new provider session."""
        ...

    async def request_password_reset(
        self,
        *,
        email: str,
        redirect_to: str | None = None,
    ) -> None:
        """Initiate a password-reset flow."""
        ...

    async def confirm_password_reset(
        self,
        *,
        email: str,
        token: str,
        new_password: str,
    ) -> None:
        """Complete a password-reset flow."""
        ...

    async def request_email_verification(
        self,
        *,
        email: str,
        redirect_to: str | None = None,
    ) -> None:
        """Request or resend an email-verification message."""
        ...

    async def confirm_email_verification(
        self,
        *,
        email: str,
        token: str,
    ) -> ProviderUserProfile:
        """Confirm an email-verification challenge and return the verified profile."""
        ...

    async def logout(self, *, access_token: str) -> None:
        """Invalidate the current provider session when supported."""
        ...

    def validate_configuration(self) -> None:
        """Validate provider configuration for readiness checks."""
        ...
