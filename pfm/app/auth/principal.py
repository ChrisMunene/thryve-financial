"""Application-facing authenticated principal."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.auth.claims import VerifiedClaims
from app.auth.types import AuthenticatedUser


class Principal(BaseModel):
    """Trusted caller context available to request handlers and services."""

    subject_id: str
    user_id: uuid.UUID
    actor_type: Literal["user", "service_account"] = "user"
    session_id: str | None = None
    tenant_id: uuid.UUID | None = None
    issuer: str | None = None
    audience: str | list[str] | None = None
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_authenticated_user(
        cls,
        *,
        user: AuthenticatedUser,
        claims: VerifiedClaims,
    ) -> "Principal":
        return cls(
            subject_id=claims.subject_id,
            user_id=user.id,
            actor_type=user.actor_type,
            session_id=claims.session_id or claims.jwt_id,
            tenant_id=user.tenant_id,
            issuer=claims.issuer,
            audience=claims.audience,
            email=user.email or claims.email,
            roles=claims.roles,
            scopes=claims.scopes,
            metadata=dict(claims.metadata),
        )
