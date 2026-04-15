"""Combined authenticated user and principal context."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.principal import Principal
from app.auth.types import AuthenticatedUser


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Authenticated application user plus the trusted auth principal."""

    user: AuthenticatedUser
    principal: Principal
