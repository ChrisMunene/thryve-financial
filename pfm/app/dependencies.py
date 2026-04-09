"""
Shared FastAPI dependencies.

All services, auth, and database access are injected via Depends().
Tests override these via app.dependency_overrides.
"""

from collections.abc import Callable

from fastapi import Depends, Request

from app.auth.delegate import AuthDelegate
from app.auth.schemas import CurrentUser
from app.auth.service import AuthService
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.db.session import get_db as get_db  # noqa: PLC0414 — re-export for DI


# --- Auth ---


_auth_delegate: AuthDelegate | None = None


def _get_auth_delegate() -> AuthDelegate:
    """Returns the auth delegate singleton. Override in tests with MockAuthDelegate."""
    global _auth_delegate
    if _auth_delegate is None:
        from app.auth.supabase import SupabaseAuthDelegate
        _auth_delegate = SupabaseAuthDelegate()
    return _auth_delegate


def _get_auth_service(
    delegate: AuthDelegate = Depends(_get_auth_delegate),
) -> AuthService:
    return AuthService(delegate=delegate)


async def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(_get_auth_service),
) -> CurrentUser:
    """Extract Bearer token from Authorization header and authenticate.

    Returns a typed CurrentUser object.
    Raises AuthenticationError if the token is missing or invalid.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthenticationError("Missing or invalid Authorization header")

    token = auth_header[7:]  # Strip "Bearer "
    if not token:
        raise AuthenticationError("Empty token")

    current_user = await auth_service.authenticate(token)
    request.state.current_user = current_user
    request.state.user_id = str(current_user.user_id)
    return current_user


def require_role(*required_roles: str) -> Callable:
    """Composable dependency that checks user roles.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint(...): ...
    """
    if not required_roles:
        raise ValueError("require_role() must be called with at least one role")

    async def _check_role(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not any(role in current_user.roles for role in required_roles):
            raise AuthorizationError(
                f"Requires one of roles: {', '.join(required_roles)}"
            )
        return current_user

    return _check_role


def require_permission(permission: str) -> Callable:
    """Composable dependency for future ABAC extension.

    Currently checks if the permission string is in the user's roles.
    Will be extended to support attribute-based checks.
    """

    async def _check_permission(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        # For now, permissions are treated as roles. Extend later.
        if permission not in current_user.roles:
            raise AuthorizationError(f"Missing permission: {permission}")
        return current_user

    return _check_permission
