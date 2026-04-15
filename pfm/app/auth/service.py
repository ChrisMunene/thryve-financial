"""Application-facing auth facade."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.principal import Principal
from app.auth.provider import AuthProvider, ProviderSession, ProviderUserProfile
from app.auth.repository import AuthRepository
from app.auth.types import (
    AuthActionResult,
    AuthIdentity,
    AuthSession,
    AuthenticatedUser,
    PasswordSignUpResult,
)
from app.core.context import set_current_user_id
from app.core.exceptions import (
    AccountNotProvisionedError,
    DependencyUnavailableError,
    ProblemException,
    ResourceNotFoundError,
)

logger = structlog.get_logger()


class AuthService:
    """Central auth interface used by the application."""

    def __init__(
        self,
        *,
        provider: AuthProvider,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def authenticate_request(self, access_token: str) -> Principal:
        claims = await self._provider_call(
            self._provider.verify_access_token(access_token),
            operation="verify_access_token",
        )

        async with self._session_factory() as session:
            repo = AuthRepository(session)
            identity = await repo.get_identity(
                provider=self.provider_name,
                issuer=claims.issuer,
                subject_id=claims.subject_id,
            )
            if identity is None:
                raise AccountNotProvisionedError.default()

            user = await repo.get_user_by_id(identity.user_id)
            if user is None or not user.is_active:
                raise AccountNotProvisionedError.default()

            authenticated_user = self._to_authenticated_user(
                user=user,
                identities=await repo.list_identities_for_user(user.id),
                principal=claims,
            )

        principal = Principal.from_authenticated_user(user=authenticated_user, claims=claims)
        set_current_user_id(str(principal.user_id))

        logger.debug(
            "auth.request_authenticated",
            provider=self.provider_name,
            user_id=str(principal.user_id),
            subject_id=principal.subject_id,
        )
        return principal

    async def sign_up_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> PasswordSignUpResult:
        result = await self._provider_call(
            self._provider.sign_up_with_password(
                email=email,
                password=password,
                display_name=display_name,
            ),
            operation="sign_up_with_password",
        )

        if result.session is None:
            logger.info(
                "auth.sign_up_pending_verification",
                provider=self.provider_name,
                email=email,
            )
            return PasswordSignUpResult(
                email=email,
                requires_email_verification=result.requires_email_verification,
            )

        session = await self._materialize_auth_session(result.session)
        return PasswordSignUpResult(
            email=email,
            requires_email_verification=False,
            session=session,
            user=session.user,
        )

    async def sign_in_with_password(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthSession:
        provider_session = await self._provider_call(
            self._provider.sign_in_with_password(email=email, password=password),
            operation="sign_in_with_password",
        )
        return await self._materialize_auth_session(provider_session)

    async def refresh_session(self, *, refresh_token: str) -> AuthSession:
        provider_session = await self._provider_call(
            self._provider.refresh_session(refresh_token=refresh_token),
            operation="refresh_session",
        )
        return await self._materialize_auth_session(provider_session)

    async def request_password_reset(self, *, email: str) -> AuthActionResult:
        await self._provider_call(
            self._provider.request_password_reset(email=email),
            operation="request_password_reset",
        )
        logger.info("auth.password_reset_requested", provider=self.provider_name, email=email)
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
        await self._provider_call(
            self._provider.confirm_password_reset(
                email=email,
                token=token,
                new_password=new_password,
            ),
            operation="confirm_password_reset",
        )
        logger.info("auth.password_reset_confirmed", provider=self.provider_name, email=email)
        return AuthActionResult(message="Your password has been updated.")

    async def request_email_verification(self, *, email: str) -> AuthActionResult:
        await self._provider_call(
            self._provider.request_email_verification(email=email),
            operation="request_email_verification",
        )
        logger.info("auth.email_verification_requested", provider=self.provider_name, email=email)
        return AuthActionResult(
            message="If an account exists for that email, verification instructions have been sent."
        )

    async def confirm_email_verification(
        self,
        *,
        email: str,
        token: str,
    ) -> AuthActionResult:
        provider_user = await self._provider_call(
            self._provider.confirm_email_verification(email=email, token=token),
            operation="confirm_email_verification",
        )
        await self._upsert_local_user(provider_user, mark_last_login=False)
        logger.info("auth.email_verification_confirmed", provider=self.provider_name, email=email)
        return AuthActionResult(message="Your email address has been verified.")

    async def logout(self, *, access_token: str) -> AuthActionResult:
        await self._provider_call(
            self._provider.logout(access_token=access_token),
            operation="logout",
        )
        logger.info("auth.logged_out", provider=self.provider_name)
        return AuthActionResult(message="You have been signed out.")

    async def get_current_user(
        self,
        *,
        user_id: UUID,
        principal: Principal | None = None,
    ) -> AuthenticatedUser:
        async with self._session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_id(user_id)
            if user is None:
                raise ResourceNotFoundError.for_resource("user", user_id)
            return self._to_authenticated_user(
                user=user,
                identities=await repo.list_identities_for_user(user.id),
                principal=principal,
            )

    def validate_configuration(self) -> None:
        self._provider.validate_configuration()

    async def _materialize_auth_session(self, provider_session: ProviderSession) -> AuthSession:
        claims = await self._provider_call(
            self._provider.verify_access_token(provider_session.access_token),
            operation="verify_access_token",
        )
        user = await self._upsert_local_user(provider_session.user, mark_last_login=True)
        user.roles = list(claims.roles)
        user.scopes = list(claims.scopes)

        logger.info(
            "auth.session_materialized",
            provider=self.provider_name,
            user_id=str(user.id),
            subject_id=provider_session.user.subject_id,
        )

        return AuthSession(
            access_token=provider_session.access_token,
            refresh_token=provider_session.refresh_token,
            token_type=provider_session.token_type,
            expires_in=provider_session.expires_in,
            user=user,
        )

    async def _upsert_local_user(
        self,
        provider_user: ProviderUserProfile,
        *,
        mark_last_login: bool,
    ) -> AuthenticatedUser:
        async with self._session_factory() as session:
            async with session.begin():
                repo = AuthRepository(session)
                identity = await repo.get_identity(
                    provider=self.provider_name,
                    issuer=provider_user.issuer,
                    subject_id=provider_user.subject_id,
                )

                if identity is not None:
                    user = await repo.get_user_by_id(identity.user_id)
                    if user is None:
                        raise AccountNotProvisionedError.default()
                    repo.sync_user_profile(
                        user,
                        email=provider_user.email,
                        display_name=provider_user.display_name,
                        email_verified_at=provider_user.email_verified_at,
                    )
                    repo.sync_identity_profile(
                        identity,
                        email=provider_user.email,
                        email_verified_at=provider_user.email_verified_at,
                        last_sign_in_at=provider_user.last_sign_in_at,
                        provider_metadata=provider_user.metadata,
                    )
                else:
                    if not provider_user.email:
                        raise AccountNotProvisionedError.default()

                    user = await repo.get_user_by_email(provider_user.email)
                    if user is None:
                        user = await repo.create_user(
                            email=provider_user.email,
                            display_name=provider_user.display_name,
                            email_verified_at=provider_user.email_verified_at,
                        )
                    else:
                        repo.sync_user_profile(
                            user,
                            email=provider_user.email,
                            display_name=provider_user.display_name,
                            email_verified_at=provider_user.email_verified_at,
                        )

                    identity = await repo.create_identity(
                        user_id=user.id,
                        provider=self.provider_name,
                        issuer=provider_user.issuer,
                        subject_id=provider_user.subject_id,
                        email=provider_user.email,
                        email_verified_at=provider_user.email_verified_at,
                        last_sign_in_at=provider_user.last_sign_in_at,
                        provider_metadata=provider_user.metadata,
                    )

                if mark_last_login:
                    AuthRepository.touch_last_login(
                        user,
                        provider_user.last_sign_in_at or datetime.now(UTC),
                    )

                identities = await repo.list_identities_for_user(user.id)
                return self._to_authenticated_user(user=user, identities=identities)

    @staticmethod
    def _to_authenticated_user(
        *,
        user,
        identities,
        principal: Principal | VerifiedClaims | None = None,
    ) -> AuthenticatedUser:
        roles: list[str] = []
        scopes: list[str] = []
        tenant_id = None
        actor_type = "user"
        if principal is not None:
            roles = list(getattr(principal, "roles", []))
            scopes = list(getattr(principal, "scopes", []))
            tenant_id = getattr(principal, "tenant_id", None)
            actor_type = getattr(principal, "actor_type", "user")

        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified_at=user.email_verified_at,
            is_active=user.is_active,
            tenant_id=tenant_id,
            actor_type=actor_type,
            roles=roles,
            scopes=scopes,
            identities=[
                AuthIdentity(
                    provider=identity.provider,
                    issuer=identity.issuer,
                    subject_id=identity.subject_id,
                    email=identity.email,
                    email_verified_at=identity.email_verified_at,
                    last_sign_in_at=identity.last_sign_in_at,
                    metadata=dict(identity.provider_metadata),
                )
                for identity in identities
            ],
        )

    @staticmethod
    async def _provider_call(coro, *, operation: str):
        try:
            return await coro
        except ProblemException:
            raise
        except Exception as exc:
            raise DependencyUnavailableError.for_service(
                "auth",
                detail="Authentication is temporarily unavailable.",
                extra_log_context={
                    "auth_reason": "provider_error",
                    "auth_operation": operation,
                    "provider_error_type": type(exc).__name__,
                },
            ) from exc
