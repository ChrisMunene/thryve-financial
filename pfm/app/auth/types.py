"""Application-facing auth DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AuthIdentity(BaseModel):
    """A linked external identity as surfaced by the auth subsystem."""

    provider: str
    issuer: str
    subject_id: str
    email: str | None = None
    email_verified_at: datetime | None = None
    last_sign_in_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthenticatedUser(BaseModel):
    """The local application user returned by auth flows."""

    id: UUID
    email: str
    display_name: str | None = None
    email_verified_at: datetime | None = None
    is_active: bool = True
    tenant_id: UUID | None = None
    actor_type: Literal["user", "service_account"] = "user"
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    identities: list[AuthIdentity] = Field(default_factory=list)


class AuthSession(BaseModel):
    """Session returned by successful sign-in and refresh flows."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    user: AuthenticatedUser


class PasswordSignUpResult(BaseModel):
    """Result for password sign-up flows that may require email verification."""

    email: str
    requires_email_verification: bool = False
    session: AuthSession | None = None
    user: AuthenticatedUser | None = None


class AuthActionResult(BaseModel):
    """Simple success message for non-session auth flows."""

    message: str
