"""
Shared FastAPI dependencies.

All services, auth, and database access are injected via Depends().
Tests override these via app.dependency_overrides.
"""

from collections.abc import Callable

import redis.asyncio as aioredis
from fastapi import Depends, Request, Security

from app.auth.auth_context import AuthContext
from app.auth.bearer import get_bearer_token
from app.auth.principal import Principal
from app.auth.service import AuthService
from app.auth.supabase import SupabaseAuthProvider
from app.clients.plaid import PlaidClient, get_plaid_client
from app.core.exceptions import PermissionDeniedError
from app.db.redis import RedisService
from app.db.session import get_async_session_factory
from app.db.session import get_db as get_db
from app.services.transactions import TransactionImportService

__all__ = [
    "get_auth_service",
    "require_auth",
    "require_user",
    "require_roles",
    "require_scopes",
    "get_db",
    "get_redis_service",
    "get_transaction_import_service",
]


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Return the application auth service singleton. Override in tests as needed."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService(
            provider=SupabaseAuthProvider(),
            session_factory=get_async_session_factory(),
        )
    return _auth_service


def get_transaction_import_service(
    plaid_client: PlaidClient = Depends(get_plaid_client),
) -> TransactionImportService:
    return TransactionImportService(plaid_client=plaid_client)


def get_redis_service(request: Request) -> RedisService:
    redis_service = getattr(request.app.state, "redis", None)
    if redis_service is None:
        raise RuntimeError("Redis service is not initialized on app.state")
    return redis_service


async def require_auth(
    request: Request,
    token: str = Security(get_bearer_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> Principal:
    """Authenticate the caller and attach the trusted principal to request state."""
    principal = await auth_service.authenticate_request(token)
    request.state.principal = principal
    request.state.subject_id = principal.subject_id
    request.state.user_id = str(principal.user_id)
    return principal


async def require_user(
    request: Request,
    principal: Principal = Security(require_auth),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthContext:
    """Load the authenticated application user together with the trusted principal."""
    user = await auth_service.get_current_user(user_id=principal.user_id, principal=principal)
    auth_context = AuthContext(user=user, principal=principal)
    request.state.current_user = user
    request.state.auth_context = auth_context
    return auth_context


def require_roles(*required_roles: str) -> Callable:
    """Composable dependency that checks principal roles."""
    if not required_roles:
        raise ValueError("require_roles() must be called with at least one role")

    async def _check_role(principal: Principal = Security(require_auth)) -> Principal:
        if not any(role in principal.roles for role in required_roles):
            raise PermissionDeniedError.missing_role(*required_roles)
        return principal

    return _check_role


def require_scopes(*required_scopes: str) -> Callable:
    """Composable dependency that checks principal scopes."""
    if not required_scopes:
        raise ValueError("require_scopes() must be called with at least one scope")

    async def _check_scopes(principal: Principal = Security(require_auth)) -> Principal:
        if not all(scope in principal.scopes for scope in required_scopes):
            raise PermissionDeniedError.missing_permission(" ".join(required_scopes))
        return principal

    return _check_scopes
