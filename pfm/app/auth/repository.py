"""Persistence helpers for the auth subsystem."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth_identity import AuthIdentityRecord
from app.models.user import User


class AuthRepository:
    """Repository for local users and auth identity mappings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        statement = (
            select(User)
            .options(selectinload(User.auth_identities))
            .where(User.id == user_id)
        )
        return await self._session.scalar(statement)

    async def get_user_by_email(self, email: str) -> User | None:
        statement = (
            select(User)
            .options(selectinload(User.auth_identities))
            .where(User.email == email)
        )
        return await self._session.scalar(statement)

    async def get_identity(
        self,
        *,
        provider: str,
        issuer: str,
        subject_id: str,
    ) -> AuthIdentityRecord | None:
        statement = select(AuthIdentityRecord).where(
            AuthIdentityRecord.provider == provider,
            AuthIdentityRecord.issuer == issuer,
            AuthIdentityRecord.subject_id == subject_id,
        )
        return await self._session.scalar(statement)

    async def list_identities_for_user(self, user_id: UUID) -> list[AuthIdentityRecord]:
        statement = select(AuthIdentityRecord).where(AuthIdentityRecord.user_id == user_id)
        return list((await self._session.scalars(statement)).all())

    async def create_user(
        self,
        *,
        email: str,
        display_name: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> User:
        user = User(
            email=email,
            display_name=display_name,
            email_verified_at=email_verified_at,
            is_active=True,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def create_identity(
        self,
        *,
        user_id: UUID,
        provider: str,
        issuer: str,
        subject_id: str,
        email: str | None,
        email_verified_at: datetime | None,
        last_sign_in_at: datetime | None,
        provider_metadata: dict,
    ) -> AuthIdentityRecord:
        identity = AuthIdentityRecord(
            user_id=user_id,
            provider=provider,
            issuer=issuer,
            subject_id=subject_id,
            email=email,
            email_verified_at=email_verified_at,
            last_sign_in_at=last_sign_in_at,
            provider_metadata=provider_metadata,
        )
        self._session.add(identity)
        await self._session.flush()
        return identity

    @staticmethod
    def touch_last_login(user: User, at: datetime | None = None) -> None:
        user.last_login_at = at or datetime.now(timezone.utc)

    @staticmethod
    def sync_user_profile(
        user: User,
        *,
        email: str | None,
        display_name: str | None,
        email_verified_at: datetime | None,
    ) -> None:
        if email:
            user.email = email
        if display_name is not None:
            user.display_name = display_name
        if email_verified_at is not None:
            user.email_verified_at = email_verified_at

    @staticmethod
    def sync_identity_profile(
        identity: AuthIdentityRecord,
        *,
        email: str | None,
        email_verified_at: datetime | None,
        last_sign_in_at: datetime | None,
        provider_metadata: dict,
    ) -> None:
        identity.email = email
        if email_verified_at is not None:
            identity.email_verified_at = email_verified_at
        if last_sign_in_at is not None:
            identity.last_sign_in_at = last_sign_in_at
        identity.provider_metadata = dict(provider_metadata)
