"""Normalized verified token claims."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class VerifiedClaims(BaseModel):
    """Trusted, normalized claims returned by the token verifier."""

    model_config = ConfigDict(populate_by_name=True)

    subject_id: str = Field(
        validation_alias=AliasChoices("sub", "subject_id", "user_id"),
    )
    issuer: str = Field(validation_alias=AliasChoices("iss", "issuer"))
    audience: str | list[str] = Field(validation_alias=AliasChoices("aud", "audience"))
    expires_at: int = Field(validation_alias=AliasChoices("exp", "expires_at"))
    issued_at: int = Field(validation_alias=AliasChoices("iat", "issued_at"))
    not_before: int | None = Field(
        default=None,
        validation_alias=AliasChoices("nbf", "not_before"),
    )
    jwt_id: str | None = Field(default=None, validation_alias=AliasChoices("jti", "jwt_id"))
    session_id: str | None = None
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_claims: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_claims(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        claims = dict(value)
        claims["raw_claims"] = dict(value)

        roles = claims.get("roles")
        if roles is None:
            role = claims.get("role")
            if isinstance(role, str) and role:
                roles = [role]
            else:
                app_metadata = claims.get("app_metadata")
                if isinstance(app_metadata, dict):
                    metadata_roles = app_metadata.get("roles")
                    if isinstance(metadata_roles, list):
                        roles = [str(item) for item in metadata_roles if item]
        if roles is not None:
            claims["roles"] = [str(item) for item in roles if item]

        scopes = claims.get("scopes")
        if scopes is None:
            if isinstance(claims.get("scope"), str):
                scopes = claims["scope"].split()
            elif isinstance(claims.get("scp"), list):
                scopes = claims["scp"]
            elif isinstance(claims.get("scp"), str):
                scopes = claims["scp"].split()
        if scopes is not None:
            claims["scopes"] = [str(item) for item in scopes if item]

        metadata = claims.get("metadata")
        if metadata is None:
            user_metadata = claims.get("user_metadata")
            if isinstance(user_metadata, dict):
                metadata = user_metadata
        if metadata is not None:
            claims["metadata"] = dict(metadata)

        session_id = claims.get("session_id")
        if session_id is None:
            session_id = claims.get("sid")
        if session_id is not None:
            claims["session_id"] = str(session_id)

        return claims
