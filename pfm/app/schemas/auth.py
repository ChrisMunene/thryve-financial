"""Schemas for auth requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr

from app.auth.types import AuthActionResult, AuthSession, AuthenticatedUser, PasswordSignUpResult


class PasswordSignUpRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: SecretStr = Field(..., min_length=8, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)


class PasswordSignInRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: SecretStr = Field(..., min_length=8, max_length=256)


class RefreshSessionRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=2048)


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class PasswordResetConfirmRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    token: str = Field(..., min_length=1, max_length=2048)
    new_password: SecretStr = Field(..., min_length=8, max_length=256)


class EmailVerificationRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class EmailVerificationConfirmRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    token: str = Field(..., min_length=1, max_length=2048)


__all__ = [
    "AuthActionResult",
    "AuthSession",
    "AuthenticatedUser",
    "EmailVerificationConfirmRequest",
    "EmailVerificationRequest",
    "PasswordResetConfirmRequest",
    "PasswordResetRequest",
    "PasswordSignInRequest",
    "PasswordSignUpRequest",
    "PasswordSignUpResult",
    "RefreshSessionRequest",
]
